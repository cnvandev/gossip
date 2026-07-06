import asyncio
import logging
from asyncio import AbstractEventLoop
from asyncio.transports import BaseTransport, DatagramTransport
from typing import Any, Callable, Coroutine, cast, override

from gossip.asyncio.protocol.multicast import MulticastDatagramProtocol
from gossip.network.endpoint import Endpoint

log = logging.getLogger(__name__)


class DatagramCallbackProtocol(MulticastDatagramProtocol):
    """A DatagramProtocol that calls a callback for each new datagram."""

    loop: AbstractEventLoop

    """The function to call."""
    callback: Callable[[bytes, Endpoint, DatagramTransport], Coroutine[Any, Any, None]]

    def __init__(self, callback: Callable[[bytes, Endpoint, DatagramTransport], Coroutine[Any, Any, None]], loop: AbstractEventLoop | None = None, group_address: str | None = None, interface_address: str | None = None):
        self.callback = callback
        self.loop = loop or asyncio.get_event_loop()
        super().__init__(group_address, interface_address)

    @override
    def connection_made(self, transport: BaseTransport):
        super().connection_made(transport)
        self.transport = cast(DatagramTransport, transport)

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        super().datagram_received(data, addr)
        future = self.callback(data, Endpoint.for_addr(addr), self.transport)
        self.loop.create_task(future)
