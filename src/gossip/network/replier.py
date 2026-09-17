import asyncio
import logging
from asyncio import Server
from asyncio.streams import StreamReader, StreamWriter
from asyncio.transports import DatagramTransport
from collections.abc import Awaitable, Callable, Iterable, Mapping
from ipaddress import IPv4Address, IPv6Address

from gossip.network.endpoint import Endpoint
from gossip.network.radio import Radio
from gossip.network.serializer import Serializable

log = logging.getLogger(__name__)


class Replier[Prompt: Serializable]:
    """A listener for prompt messages, replying appropriately with a message.

    Takes a mapping of TCP/UDP ports to async deserializer functions which
    return our typed prompt objects from the stream/datagram. Each incoming
    prompt is passed to the callback function, and if a reply is returned, it is
    sent back on the same transport. Subclasses can implement protocols which
    use other transports by returning None from the callback function in those
    cases.

    A TCP connection is kept open for more than one prompt/reply cycle
    as long as the last reply isn't terminal - closed once it is, once
    the deserializer returns `None` (nothing more to read), or once
    `tcp_idle_timeout` seconds pass without a new prompt arriving.
    """

    radio: Radio
    callback: Callable[[Prompt, Endpoint, Endpoint], Awaitable[Iterable[Serializable]]]
    tcp: Mapping[int, Callable[[StreamReader], Awaitable[Prompt | None]]]
    udp: Mapping[int | Endpoint, Callable[[tuple[bytes, Endpoint]], Awaitable[Prompt | None]]]

    """How long a TCP connection may sit idle, awaiting its next prompt,
    before it's closed. `None` (the default) waits indefinitely."""
    tcp_idle_timeout: float | None

    """The TCP servers and UDP transports opened by `__aenter__()` -
    empty until entered, closed again by `__aexit__()`."""
    tcp_servers: tuple[Server, ...]
    udp_transports: tuple[DatagramTransport, ...]

    def __init__(
        self,
        callback: Callable[[Prompt, Endpoint, Endpoint], Awaitable[Iterable[Serializable]]],
        tcp: Mapping[int, Callable[[StreamReader], Awaitable[Prompt | None]]] | None = None,
        udp: Mapping[int | Endpoint, Callable[[tuple[bytes, Endpoint]], Awaitable[Prompt | None]]] | None = None,
        radio: Radio | None = None,
        tcp_idle_timeout: float | None = None,
        *args,
        **kwargs,
    ):
        self.callback = callback
        self.tcp = tcp or {}
        self.udp = udp or {}
        self.radio = radio or Radio.from_netifaces()
        self.tcp_idle_timeout = tcp_idle_timeout
        self.tcp_servers = ()
        self.udp_transports = ()
        super().__init__(*args, **kwargs)

    async def __aenter__(self):
        """Start listening for prompts."""
        listeners = ()
        port_strings = ()

        # Set up our TCP listeners
        for port, tcp_deserializer in self.tcp.items():

            async def tcp_callback(tcp_reader: StreamReader, tcp_writer: StreamWriter, deserializer: Callable[[StreamReader], Awaitable[Prompt | None]] = tcp_deserializer) -> None:
                remote_address = tcp_writer.get_extra_info("peername")
                remote_endpoint = Endpoint.for_addr(remote_address)
                local_address = tcp_writer.get_extra_info("sockname")
                local_endpoint = Endpoint.for_addr(local_address)

                while True:
                    try:
                        prompt = await asyncio.wait_for(deserializer(tcp_reader), timeout=self.tcp_idle_timeout)
                    except TimeoutError:
                        log.debug("TCP %s idle for %.1fs, closing.", remote_endpoint, self.tcp_idle_timeout)
                        break

                    log.debug("Deserialized %r from TCP %s", prompt, remote_endpoint)
                    if prompt is None:
                        break

                    replies = await self.callback(prompt, remote_endpoint, local_endpoint)
                    last_reply = None
                    for reply in replies:
                        last_reply = reply
                        log.debug("Writing reply %r to TCP %s", reply, remote_endpoint)
                        await reply.write_to(tcp_writer)
                        await tcp_writer.drain()

                    if last_reply is None or last_reply.is_terminal():
                        break

                log.debug("Closing connection to TCP %s.", remote_endpoint)
                tcp_writer.close()
                await tcp_writer.wait_closed()

            listeners += (self.radio.tcp_listen(tcp_callback, port),)
            port_strings += (f"TCP port {port}",)

        # Set up our UDP listeners
        for port_or_endpoint, udp_deserializer in self.udp.items():

            async def udp_callback(datagram: bytes, local_address: IPv4Address | IPv6Address | None, remote_endpoint: Endpoint, transport: DatagramTransport, deserializer: Callable[[tuple[bytes, Endpoint]], Awaitable[Prompt | None]] = udp_deserializer) -> None:
                bound_address = transport.get_extra_info("sockname")
                bound_endpoint = Endpoint.for_addr(bound_address)
                if local_address is None:
                    log.debug("Received prompt from %s as UDP %s", remote_endpoint, bound_endpoint)
                    prompt = await deserializer((datagram, remote_endpoint))
                    log.debug("Deserialized %r as UDP %s", prompt, bound_endpoint)
                    if prompt is None:
                        return  # No prompt found, skip this callback

                    replies = tuple(await self.callback(prompt, remote_endpoint, bound_endpoint))
                    for reply in replies:
                        log.debug("Writing reply %r as UDP %s", reply, bound_endpoint)
                        transport.sendto(bytes(reply), (str(remote_endpoint.address), remote_endpoint.port))
                    log.debug("Done, closing connection to UDP %s.", local_address)
                else:
                    local_endpoint = Endpoint(local_address, bound_endpoint.port)
                    log.debug("Received prompt from %s as UDP %s (on channel %s)", remote_endpoint, local_address, bound_endpoint)

                    prompt = await deserializer((datagram, remote_endpoint))
                    log.debug("Deserialized %r from %s as UDP %s (on channel %s)", prompt, remote_endpoint, local_address, bound_endpoint)
                    if prompt is None:
                        return  # No prompt found, skip this callback

                    replies = tuple(await self.callback(prompt, remote_endpoint, local_endpoint))
                    for reply in replies:
                        log.debug("Writing reply %r as UDP %s (on channel %s)", reply, local_address, bound_endpoint)

                        # Unlike unicast messages, a new UDP send is required
                        # here since multicast doesn't leave the transport open.
                        message = bytes(reply)
                        reply_transport, _ = await self.radio.udp_send(remote_endpoint)
                        reply_transport.sendto(message)
                        reply_transport.close()

                log.debug("Done, closing connection to UDP %s.", local_address)

            # If we're given an endpoint (IP & port), we're listening on a
            # multicast socket with that group address. Otherwise, it's a
            # port to listen on for unicast messages - 0 for a random one.
            if isinstance(port_or_endpoint, Endpoint):
                listeners += (self.radio.udp_listen(udp_callback, port_or_endpoint.port, port_or_endpoint.address),)
                port_strings += (f"UDP broadcast address {port_or_endpoint}",)
            else:
                listeners += (self.radio.udp_listen(udp_callback, port_or_endpoint),)
                port_strings += (f"UDP port {port_or_endpoint}",)

        if not listeners:
            raise ValueError("At least one port or group address must be specified")

        results = await asyncio.gather(*listeners)
        self.tcp_servers = tuple(result for result in results if isinstance(result, Server))
        self.udp_transports = tuple(transport for result in results if not isinstance(result, Server) for transport, _ in result)
        log.info("%s listening on %s", self.__class__.__name__, ", ".join(port_strings))

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stop listening, closing every socket `__aenter__()` opened."""
        for server in self.tcp_servers:
            server.close()
        for transport in self.udp_transports:
            transport.close()
        if self.tcp_servers:
            await asyncio.gather(*(server.wait_closed() for server in self.tcp_servers))
