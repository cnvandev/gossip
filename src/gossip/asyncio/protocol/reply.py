import asyncio
import logging
from asyncio import AbstractEventLoop, Future
from typing import override

from gossip.asyncio.protocol.multicast import MulticastDatagramProtocol
from gossip.network.endpoint import Endpoint

log = logging.getLogger(__name__)


class DatagramReplyProtocol(MulticastDatagramProtocol):
    """A DatagramProtocol that exposes an expected reply as a `Future`."""

    """The reply we expect to receive (eventually...), or `None` if the
    connection was closed with no reply."""
    reply: Future[tuple[bytes, Endpoint] | None]

    """The event loop to schedule `Future`s."""
    loop: AbstractEventLoop

    def __init__(self, loop: AbstractEventLoop | None = None, group_address: str | None = None, interface_address: str | None = None):
        super().__init__(group_address, interface_address)

        # Make sure we have an event loop to create our reply `Future`.
        if not loop:
            loop = asyncio.get_event_loop()

        # `Future`s to hold the datagram reply we're looking for.
        self.reply = loop.create_future()

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.reply.set_result((data, Endpoint.for_addr(addr)))

    def error_received(self, exc: Exception) -> None:
        self.reply.set_exception(exc)

    @override
    def connection_lost(self, exc: Exception | None) -> None:
        super().connection_lost(exc)
        if exc is None:
            # Finish the Future if we didn't get any datagrams.
            if not self.reply.done():
                self.reply.set_result(None)
        else:
            # Set the exception, if we got one.
            self.reply.set_exception(exc)
