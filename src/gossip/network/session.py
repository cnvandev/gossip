import logging
from asyncio.streams import StreamReader, StreamWriter
from collections.abc import Awaitable, Callable
from typing import Self

from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable

log = logging.getLogger(__name__)


class PromptSession[Reply: Serializable]:
    """An open TCP connection to a single peer, for sending prompts and
    reading back their replies.

    `send()` only writes a prompt, it doesn't wait for or return the
    reply - read that back with `read_reply()`, or async-iterate the
    session (`async for`/`anext()`), which just calls `read_reply()` on
    each step and stops once it returns `None`. At most one prompt may
    be outstanding at a time: `send()` raises `RuntimeError` if called
    again before the previous reply has been read.

    A session ends itself - iteration raises `StopAsyncIteration`,
    `send()` raises `ConnectionError` - as soon as the deserializer
    returns `None` for a reply, or a reply reports `is_terminal()`.
    Either way the connection is closed immediately, before the
    triggering call raises or returns.
    """

    address: Endpoint
    reader: StreamReader
    writer: StreamWriter
    deserializer: Callable[[StreamReader], Awaitable[Reply | None]]

    """Whether a `send()`'d prompt is still waiting on its reply."""
    reply_pending: bool

    def __init__(
        self,
        address: Endpoint,
        reader: StreamReader,
        writer: StreamWriter,
        deserializer: Callable[[StreamReader], Awaitable[Reply | None]],
    ):
        self.address = address
        self.reader = reader
        self.writer = writer
        self.deserializer = deserializer
        self.reply_pending = False

    async def send(self, prompt: Serializable) -> None:
        """Write `prompt` to the connection."""
        if self.writer.is_closing():
            raise ConnectionError(f"Session to {self.address} is already closed.")
        if self.reply_pending:
            raise RuntimeError(f"Session to {self.address} already has an unread reply pending.")

        await prompt.write_to(self.writer)
        self.reply_pending = True

    async def read_reply(self) -> Reply | None:
        """Read and deserialize the next reply, or `None` if the session
        has already ended. Closes the connection first if this reply is
        the last one (see class docstring)."""
        if self.writer.is_closing():
            return None

        reply = await self.deserializer(self.reader)
        self.reply_pending = False
        if reply is None or reply.is_terminal():
            self.close()
        return reply

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Reply:
        reply = await self.read_reply()
        if reply is None:
            raise StopAsyncIteration
        return reply

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        await self.wait_closed()

    def close(self) -> None:
        """Close the connection. Safe to call more than once."""
        self.writer.close()

    async def wait_closed(self) -> None:
        """Wait for `close()` to finish."""
        await self.writer.wait_closed()
