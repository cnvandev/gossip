import asyncio
import logging
from asyncio import Future
from asyncio.queues import Queue
from asyncio.streams import StreamReader, StreamWriter
from asyncio.transports import DatagramTransport
from collections.abc import Awaitable, Callable

from aiostream import stream

from gossip.network.endpoint import Endpoint
from gossip.network.radio import Radio
from gossip.network.serializer import Serializable

log = logging.getLogger(__name__)


class Prompter[Reply: Serializable]:
    """The initiator of a connection, who also sends the first message.

    It opens the connections and sends the initial serializable message, the
    other side of the connection is the replier, who sends the reply message.

    Works bi-directionally with both TCP and UDP, making it usable in unicast,
    multicast, and broadcast request scenarios. Prompts and replies need to
    implement `Serializable` to be compatible.
    """

    """The network device used for sending and receiving messages."""
    radio: Radio

    """The function used to deserialize typed `Reply` messages."""
    deserializer: Callable[
        [StreamReader | tuple[bytes, Endpoint]],
        Awaitable[Reply | None],
    ]

    def __init__(
        self,
        deserializer: Callable[
            [StreamReader | tuple[bytes, Endpoint]],
            Awaitable[Reply | None],
        ],
        radio: Radio | None = None,
    ):
        self.radio = radio or Radio.from_netifaces()
        self.deserializer = deserializer

    async def prompt_tcp(self, prompt: Serializable, address: Endpoint) -> Reply | None:
        """Sends a prompt message to the given address, awaiting the reply.

        Asynchronously returns the reply, or `None` if the reply is not
        acceptable by our deserializer.
        """
        reader, writer = await self.radio.tcp_send(address)
        log.debug("Connected to TCP %s, sending prompt %r", address, prompt)
        await prompt.write_to(writer)
        log.info("Sent prompt to TCP %s", address)
        reply = await self.deserializer(reader)
        log.info("Received reply %r from TCP %s", reply, address)
        writer.close()
        await writer.wait_closed()
        return reply

    async def prompt_udp(self, prompt: Serializable, remote_host: Endpoint, tcp_port: int | None = None) -> Reply | None:
        """Sends out a prompt via UDP to the given endpoint, then waits for a
        reply over UDP (or TCP, if specified).
        """
        ttl = 1  # Unicast search always times out after 1 second.

        loop = asyncio.get_running_loop()
        reply_future: Future[Reply | None] = loop.create_future()
        transport, reply_protocol = await self.radio.udp_send(remote_host)
        log.debug("Connected to UDP %s, sending prompt %r", remote_host, prompt)

        # Listen for a reply on TCP or UDP, whichever is specified. This must
        # happen before we send the message so we have the outgoing port
        # to tell people to reply on (i.e. on a `Host` header in the message).
        if tcp_port is not None:
            log.debug("Listening for replies on TCP: %s", tcp_port)

            async def tcp_callback(reader: StreamReader, _: StreamWriter):
                reply = await self.deserializer(reader)
                if reply is not None:
                    reply_future.set_result(reply)

            _ = await self.radio.tcp_listen(tcp_callback, tcp_port)
        else:
            # Otherwise we'll just use the existing UDP transport.
            _, udp_port = transport.get_extra_info("sockname")
            log.debug("Listening for replies on existing UDP: %s", udp_port)

            async def udp_callback(data_future: Awaitable[tuple[bytes, Endpoint] | None]):
                result = await data_future
                if result is not None:
                    reply = await self.deserializer(result)
                    if reply is not None:
                        return reply
                    else:
                        # No reply, nothing to send back.
                        return None
                else:
                    # No data received, nothing to deserialize.
                    return None

            # Because we don't have to wait for a connection, we can just return a task.
            reply_future = asyncio.create_task(udp_callback(reply_protocol.reply))

        serialized = bytes(prompt)
        transport.sendto(serialized)
        log.info("Sent %r (%d bytes) to %s.", prompt, len(serialized), remote_host)

        return await asyncio.wait_for(reply_future, timeout=ttl)

    async def broadcast(self, prompt: Serializable | Callable[[Endpoint], Serializable], host: Endpoint) -> None:
        """Sends out a prompt broadcast datagram, ignoring replies."""
        # We'll iterate on all interfaces that our radio is configured to use.
        connections = []
        for transport, protocol in await self.radio.udp_broadcast(host.address, host.port):
            connections.append(protocol.reply)
            # Open the connection to send the request.
            local_address = Endpoint.for_addr(transport.get_extra_info("sockname"))

            # Generate the prompt message, either the fixed message or
            # generated using the local address.
            if isinstance(prompt, Callable):
                prompt = prompt(local_address)

            # Finally, send the actual message via the protocol.
            serialized = bytes(prompt)
            log.info("Broadcast %r (%d bytes) on %s.", prompt, len(serialized), host)
            transport.sendto(serialized)
            transport.close()

        await asyncio.gather(*connections)

    async def broadcast_prompt(self, prompt: Serializable | Callable[[Endpoint], Serializable], host: Endpoint, tcp_port: int | None = None, max_wait: int = 5):
        """Sends out a datagram message on the address and listens for replies."""
        queue: Queue[Reply] = Queue()
        log.info("Broadcasting %r on all interfaces.", prompt)
        # We'll iterate on all interfaces that our radio is configured to use.
        for interface in self.radio.interfaces.values():
            # Open the connection to send the request.
            broadcast_transport, _ = await interface.udp_broadcast(host.address, host.port)
            local_address = Endpoint.for_addr(broadcast_transport.get_extra_info("sockname"))
            log.debug("Connected to UDP broadcast socket as %s, sending prompt %r", local_address, prompt)

            # Our UDP connection is already open, but if requested we can listen
            # for a reply on TCP. This must happen before we send the message
            # so we have the outgoing port to tell people to reply on (via the
            # `Host` header, or whatever the protocol dictates.)
            if tcp_port is not None:
                log.debug("Listening for broadcast replies on TCP: %s", tcp_port)

                async def tcp_callback(reader: StreamReader, writer: StreamWriter):
                    remote_address = writer.get_extra_info("peername")
                    endpoint = Endpoint.for_addr(remote_address)
                    log.debug("Receiving reply from TCP %s", endpoint)

                    # This assumes broadcast replys are always headers-only
                    # messages, that can be loaded entirely into memory.
                    tcp_reply = await self.deserializer(reader)
                    if tcp_reply is not None:
                        log.debug("Deserialized reply %r from TCP %s", tcp_reply, endpoint)
                        await queue.put(tcp_reply)

                    log.debug("Done, closing connection to TCP %s.", endpoint)
                    writer.close()
                    await writer.wait_closed()

                _ = await interface.tcp_listen(tcp_callback, port=tcp_port)
            else:
                _, udp_port = broadcast_transport.get_extra_info("sockname")
                log.debug("Listening for replies on existing UDP: %s", udp_port)

                async def udp_callback(data: bytes, sender: Endpoint, _: DatagramTransport):
                    log.debug("Receiving reply from UDP %s", sender)
                    udp_reply = await self.deserializer((data, sender))
                    if udp_reply is not None:
                        log.debug("Deserialized reply %r from UDP %s", udp_reply, sender)
                        await queue.put(udp_reply)
                    log.debug("Done, closing connection to UDP %s.", sender)

                # Broadcast prompt are sent on the transport, but replies are
                # received directly to the sender endpoint, so we'll listen for
                # non-multicast replies.
                _ = await interface.udp_listen(udp_callback, port=udp_port)

            # Generate the prompt message using the local address if we need.
            if isinstance(prompt, Callable):
                prompt = prompt(local_address)

            # Finally, send the actual message via the protocol.
            serialized = bytes(prompt)
            broadcast_transport.sendto(serialized)
            broadcast_transport.close()
            log.info("Broadcast prompt %r (%d bytes) to %s.", prompt, len(serialized), host)

        return stream.iterate(queue_iterator(queue))


async def queue_iterator[M](async_queue: Queue[M]):
    """
    An asynchronous iterator over an asyncio.Queue.
    """
    while True:
        # Wait asynchronously for an item from the queue
        log.debug("Waiting for item from queue")
        item = await async_queue.get()
        log.debug("Got an item from queue")

        # Check for a sentinel value (e.g., None) to signal the end,
        # or yield to the consumer.
        if item is None:
            log.debug("breaking the queue")
            break
        else:
            log.debug("yielding item")
            yield item
