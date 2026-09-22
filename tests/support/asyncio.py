"""Shared asyncio test helpers.

Not a test module - imported by tests that need to close something
that requires an awaited `wait_closed()`, not just a `close()` call, or
a real UDP socket that replies with a fixed (or sequenced) message.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable


class StaticReplyProtocol(asyncio.DatagramProtocol):
    """A `DatagramProtocol` that replies to every datagram it receives
    with the same fixed bytes, sent back to whoever sent it."""

    def __init__(self, reply: bytes):
        self.reply = reply

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.transport.sendto(self.reply, addr)


class SequencedReplyProtocol(asyncio.DatagramProtocol):
    """Replies with each of `replies` in turn, one per datagram received -
    the last reply repeats for any further datagrams."""

    def __init__(self, replies: list[bytes]):
        self.replies = replies
        self.count = 0

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        reply = self.replies[min(self.count, len(self.replies) - 1)]
        self.count += 1
        self.transport.sendto(reply, addr)


class MessageCollector[M: Serializable](asyncio.DatagramProtocol):
    """Collects every datagram sent to it, deserialized via `deserializer`,
    resolving `done` once `expected` of them have arrived."""

    def __init__(self, deserializer: Callable[[tuple[bytes, Endpoint]], Awaitable[M | None]], expected: int = 1):
        self.deserializer = deserializer
        self.expected = expected
        self.messages: list[M] = []
        self.done: asyncio.Future[None] = asyncio.get_event_loop().create_future()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        asyncio.get_event_loop().create_task(self.record(data, addr))

    async def record(self, data: bytes, addr: tuple[str, int]) -> None:
        message = await self.deserializer((data, Endpoint.for_addr(addr)))
        if message is not None:
            self.messages.append(message)
            if len(self.messages) >= self.expected and not self.done.done():
                self.done.set_result(None)


class _WaitsToClose(Protocol):
    def close(self) -> None: ...
    async def wait_closed(self) -> None: ...


@asynccontextmanager
async def wait_closing[T: _WaitsToClose](closeable: T) -> AsyncIterator[T]:
    """Closes `closeable` on exit, awaiting `wait_closed()` too - unlike
    `contextlib.closing()`, for things (like `asyncio.Server`/
    `asyncio.StreamWriter`) where closing needs a wait, not just a call."""
    try:
        yield closeable
    finally:
        closeable.close()
        await closeable.wait_closed()
