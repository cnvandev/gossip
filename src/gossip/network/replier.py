import asyncio
import logging
from asyncio.streams import StreamReader, StreamWriter
from asyncio.transports import DatagramTransport
from typing import Awaitable, Callable, Iterable, Mapping

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
    """

    radio: Radio
    callback: Callable[[Prompt, Endpoint, Endpoint], Awaitable[Iterable[Serializable]]]
    tcp: Mapping[int, Callable[[StreamReader], Awaitable[Prompt | None]]]
    udp: Mapping[int | Endpoint | None, Callable[[tuple[bytes, Endpoint]], Awaitable[Prompt | None]]]

    def __init__(
        self,
        callback: Callable[[Prompt, Endpoint, Endpoint], Awaitable[Iterable[Serializable]]],
        tcp: Mapping[int, Callable[[StreamReader], Awaitable[Prompt | None]]] | None = None,
        udp: Mapping[int | Endpoint | None, Callable[[tuple[bytes, Endpoint]], Awaitable[Prompt | None]]] | None = None,
        radio: Radio | None = None,
        *args,
        **kwargs,
    ):
        self.callback = callback
        self.tcp = tcp or {}
        self.udp = udp or {}
        self.radio = radio or Radio.from_netifaces()
        super().__init__(*args, **kwargs)

    async def __aenter__(self):
        """Start listening for prompts."""
        listeners = tuple()
        port_strings = tuple()

        # Set up our TCP listeners
        for port, tcp_deserializer in self.tcp.items():

            async def tcp_callback(tcp_reader: StreamReader, tcp_writer: StreamWriter) -> None:
                remote_address = tcp_writer.get_extra_info("peername")
                remote_endpoint = Endpoint.for_addr(remote_address)
                log.debug("Received prompt from TCP %s", remote_endpoint)

                prompt = await tcp_deserializer(tcp_reader)
                log.debug("Deserialized %r from TCP %s", prompt, remote_endpoint)
                if prompt is None:
                    return

                local_address = tcp_writer.get_extra_info('sockname')
                local_endpoint = Endpoint.for_addr(local_address)

                replies = await self.callback(prompt, remote_endpoint, local_endpoint)
                for reply in replies:
                    log.debug("Writing reply %r to TCP %s", reply, remote_endpoint)
                    await reply.write_to(tcp_writer)
                    await tcp_writer.drain()
                log.debug("Done, closing connection to TCP %s.", remote_endpoint)
                tcp_writer.close()
                await tcp_writer.wait_closed()

            listeners += (self.radio.tcp_listen(tcp_callback, port),)
            port_strings += (f"TCP port {port}",)

        # Set up our UDP listeners
        for port_or_endpoint, udp_deserializer in self.udp.items():

            async def udp_callback(datagram: bytes, remote_endpoint: Endpoint, transport: DatagramTransport) -> None:
                local_address = transport.get_extra_info("sockname")
                local_endpoint = Endpoint.for_addr(local_address)
                log.debug("Received prompt from %s as UDP %s", remote_endpoint, local_endpoint)

                prompt = await udp_deserializer((datagram, remote_endpoint))
                log.debug("Deserialized %r as UDP %s", prompt, local_endpoint)
                if prompt is None:
                    return  # No prompt found, skip this callback

                replies = tuple(await self.callback(prompt, remote_endpoint, local_endpoint))
                for reply in replies:
                    log.debug("Writing reply %r as UDP %s", reply, local_endpoint)
                    message = bytes(reply)
                    transport.sendto(message, (str(remote_endpoint.address), remote_endpoint.port))

                log.debug("Done, closing connection to UDP %s.", local_endpoint)

            # If we're given an endpoint (IP & port), we're listening on a
            # multicast socket with that group address. If it's an integer, we
            # listen on that port for unicast messages. Otherwise, we'll choose
            # a random port.
            if isinstance(port_or_endpoint, Endpoint):
                listeners += (self.radio.udp_listen(udp_callback, port_or_endpoint.port, port_or_endpoint.address),)
                port_strings += (f"UDP broadcast address {port_or_endpoint}",)
            elif port_or_endpoint is not None:
                listeners += (self.radio.udp_listen(udp_callback, port_or_endpoint or 0),)
                port_strings += (f"UDP port {port_or_endpoint}",)
            else:
                listeners += (self.radio.udp_listen(udp_callback),)
                port_strings += ("UDP (random port)",)

        if not listeners:
            raise ValueError("At least one port or group address must be specified")

        _ = await asyncio.gather(*listeners)
        log.info("%s listening on %s", self.__class__.__name__, ", ".join(port_strings))

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Apparently we HAVE to implement this.
        pass
