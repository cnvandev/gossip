from asyncio import Event
from asyncio.streams import StreamReader, StreamWriter
from typing import Protocol, Self, SupportsBytes, override

from gossip.network.endpoint import Endpoint

DEFAULT_LIMIT = 65536


class Serializable(SupportsBytes, Protocol):
    """Base class that defines serializability."""

    async def write_to(self, writer: StreamWriter) -> None:
        """Write ourselves to the stream via `bytes()`.

        This is the intentionally-dumb default implementation, it loads the
        serialization into memory so it might be inefficient, but for something
        that would fit into a UDP packet this is fine.

        Subclasses can override this to provide a more efficient implementation.
        """
        writer.write(bytes(self))
        await writer.drain()

    def is_terminal(self) -> bool:
        """Returns if this is the last message in a session (true by default.)"""
        return True

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None: ...


class BufferedReader(StreamReader):
    """A `StreamReader` for wrapping a buffer that's already fully in
    memory - feed it and call `feed_eof()`, same as any other
    `StreamReader`, then hand it off wherever a `StreamReader` is expected
    (e.g. as a message's `body`).

    Skips the real `StreamReader.__init__()`, which eagerly grabs the
    current event loop via `events.get_event_loop()` - unavailable when
    constructed outside a running loop (e.g. building a response
    synchronously, before any `await`). That loop reference is only ever
    used by `_wait_for_data()`, to await data that hasn't arrived yet; a
    buffer that's fed and EOF'd before anyone reads from it never needs to
    wait, so `_wait_for_data()` - and the loop - never actually gets
    touched.
    """

    def __init__(self):
        self._limit = DEFAULT_LIMIT
        self._buffer = bytearray()
        self._eof = False
        self._waiter = None
        self._exception = None
        self._transport = None
        self._paused = False
        self._closed = Event()

    @classmethod
    def for_bytes(cls, data: bytes) -> Self:
        """Builds a `BufferedReader` already fed with `data` and EOF'd,
        ready to read from - the two calls every caller needs before use,
        done once here."""
        reader = cls()
        reader.feed_data(data)
        reader.feed_eof()
        return reader

    @override
    def feed_eof(self) -> None:
        super().feed_eof()
        self._closed.set()

    async def wait_closed(self) -> None:
        """Waits until `feed_eof()` has been called - for a reader built
        via `for_bytes()`, that's already true by construction, so this
        returns immediately."""
        _ = await self._closed.wait()
