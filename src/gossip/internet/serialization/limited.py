import logging
from asyncio import IncompleteReadError
from asyncio.streams import StreamReader
from collections.abc import Buffer, Sized
from typing import Protocol, override


# This is a protocol for a buffer that can be read from and has a size, used in
# `StreamReader.readnutil()` for some reason.
class ReadableBuffer(Buffer, Sized, Protocol): ...

log = logging.getLogger(__name__)


class LimitedReader(StreamReader):
    """A `StreamReader` that reads at most `limit` bytes from `source`,
    then reports EOF regardless of how much more `source` actually has.

    Every read method delegates straight to its counterpart on `source`,
    capping the request to whatever's left of `limit` where the method's
    own signature allows it (`read()`, `readexactly()`), or truncating
    whatever comes back where it doesn't (`readline()`, `readuntil()`,
    which have no way to bound the request itself, and so can still read
    past `limit` on `source` if a line or separator lies beyond it).
    `update_count()` tracks how much has been handed back so far against
    `limit`, and calls `self.feed_eof()` the moment that total is
    reached.

    Note that in this approach, `source` itself is never `feed_eof()`'d, since
    it may still have more to give someone else after this reader is done.
    """

    source: StreamReader
    limit: int
    read_count: int

    def __init__(self, source: StreamReader, limit: int):
        super().__init__()
        self.source = source
        self.limit = limit
        self.read_count = 0
        if limit <= 0:
            self.feed_eof()

    def update_count(self, count: int) -> None:
        """Records `count` more bytes as handed back to the caller, and
        calls `feed_eof()` once `read_count` has reached the limit.
        """
        self.read_count += count
        if self.read_count >= self.limit:
            self.feed_eof()

    @override
    async def read(self, n: int = -1) -> bytes:
        """Read up to `n` bytes from `source`.

        `n` is first capped to whatever's left of `limit`, so `source` is never
        asked for more than that. Raises `EOFError` instead of returning empty
        if `source` ends before `limit` bytes have been read overall.
        """
        remaining = self.limit - self.read_count
        if remaining <= 0 or n == 0:
            return b""

        want = remaining if n < 0 else min(n, remaining)
        data = await self.source.read(want)
        if not data:
            raise EOFError(f"source ended after {self.read_count} of {self.limit} expected bytes")

        self.update_count(len(data))
        return data

    @override
    async def readline(self) -> bytes:
        """Read a chunk of data from `source` until newline is found.

        The result is truncated to whatever's left of `limit` if it overshoots
        - `readline()` has no size to cap upfront, so `source` can still be
        read past `limit` if the line itself does.
        """
        remaining = self.limit - self.read_count
        if remaining <= 0:
            return b""

        data = await self.source.readline()
        if len(data) > remaining:
            data = data[:remaining]

        self.update_count(len(data))
        return data

    @override
    async def readuntil(self, separator: ReadableBuffer | tuple[ReadableBuffer, ...] = b"\n") -> bytes:
        """Read data from `source` until `separator` is found.

        Raises `IncompleteReadError` instead of succeeding if `separator` only
        turns up beyond `limit` - same caveat as `readline()`: there's no way
        to bound the search itself, so `source` may still be read past
        `limit` to find it.
        """
        remaining = self.limit - self.read_count
        if remaining <= 0:
            raise IncompleteReadError(b"", None)

        data = await self.source.readuntil(separator)
        if len(data) > remaining:
            data = data[:remaining]
            self.update_count(len(data))
            raise IncompleteReadError(data, None)

        self.update_count(len(data))
        return data

    @override
    async def readexactly(self, n: int) -> bytes:
        """Read exactly `n` bytes from `source`.

        Raises `IncompleteReadError` itself, without touching `source` for
        more than `limit` allows, if `n` exceeds what's left of `limit`.
        """
        remaining = self.limit - self.read_count
        if n <= remaining:
            data = await self.source.readexactly(n)
            self.update_count(len(data))
            return data

        partial = await self.source.readexactly(remaining) if remaining > 0 else b""
        self.update_count(len(partial))
        raise IncompleteReadError(partial, n)
