import asyncio
from asyncio.streams import StreamReader, StreamWriter
from collections.abc import Callable
from typing import Protocol, Self, SupportsBytes

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

    @classmethod
    def for_bytes(cls, data: bytes) -> Self:
        """Builds a `BufferedReader` already fed with `data` and EOF'd,
        ready to read from - the two calls every caller needs before use,
        done once here."""
        reader = cls()
        reader.feed_data(data)
        reader.feed_eof()
        return reader


class BoundedReader(StreamReader):
    """A `StreamReader` that pumps `source` into itself, stopping at
    exactly `limit` bytes - or, if `limit` is `None`, pumping everything
    until `source` itself ends. Either way, this reports EOF the moment
    its pump is done - for a real `limit`, that's regardless of what's
    left on `source` behind it (e.g. the next pipelined message on the
    same connection, or trailers that don't belong to this body).

    `limit`'s presence or absence is exactly the standards-compliant
    signal for whether trailers can exist at all: `Content-Length` and
    trailers are mutually exclusive in HTTP (RFC 9112 §6.3), so a body
    given a real `limit` (from a `Content-Length`) provably has none once
    exhausted, while a `None` limit (no `Content-Length`) leaves that an
    open question for whoever's tracking it.

    Calls `on_exhausted()` (if given) exactly once, the moment the pump
    finishes - reaching `limit`, or `source` ending (early, for a bounded
    pump; naturally, for an unbounded one). This fires from the pump task
    itself, independent of whoever (if anyone) is actually reading `self`
    - a caller reading `self` directly gets the same cutoff as one going
    through a higher-level helper.

    Unlike `BufferedReader`, this needs a running event loop to construct:
    it starts that pump task immediately, and a real, loop-bound
    `StreamReader` (not the loop-free trick `BufferedReader` uses) is what
    the pump's `feed_data()`/`feed_eof()` calls need on the receiving end.

    A bounded source that ends before delivering `limit` bytes isn't
    treated as an error - `self` just ends up shorter than `limit`, same
    as a real connection closing early. Nothing here buffers unboundedly
    either: the pump reads in the same chunk size `BufferedReader` limits
    to, so an unconsumed `self` grows at most one chunk past `limit` (or,
    unbounded, one chunk at a time) - but it does mean the pump keeps
    pulling from `source` regardless of whether anything is actually
    draining `self`.
    """

    def __init__(self, source: StreamReader, limit: int | None, on_exhausted: Callable[[], None] | None = None):
        super().__init__()
        self._pump_task = asyncio.get_running_loop().create_task(self._pump(source, limit, on_exhausted))

    async def _pump(self, source: StreamReader, limit: int | None, on_exhausted: Callable[[], None] | None) -> None:
        remaining = limit
        try:
            while remaining is None or remaining > 0:
                chunk_size = DEFAULT_LIMIT if remaining is None else min(remaining, DEFAULT_LIMIT)
                chunk = await source.read(chunk_size)
                if not chunk:
                    break
                self.feed_data(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
        finally:
            self.feed_eof()
            if on_exhausted is not None:
                on_exhausted()
