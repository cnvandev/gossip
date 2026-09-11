import logging
import zlib
from abc import ABC, abstractmethod
from asyncio import IncompleteReadError
from asyncio.streams import StreamReader
from collections.abc import Buffer, Sized
from typing import Final, Protocol, override


# This is a protocol for a buffer that can be read from and has a size, used in
# `StreamReader.readuntil()` for some reason.
class ReadableBuffer(Buffer, Sized, Protocol): ...


log = logging.getLogger(__name__)


class EncodedReader(StreamReader, ABC):
    """A `StreamReader` that decodes a transfer-coding, by reading raw
    bytes off a source `StreamReader` and decoding them for return.

    A single `decode()` step rarely lines up with what a caller actually
    asked for, so every read method below pulls more via `decode()` until it has
    enough, stores any excess in `self.overflow`, and drains that first on the
    next call before pulling anything new. `self.feed_eof()` is called once
    `decode()` has reported `None` and `self.overflow` is fully drained,
    so `self.at_eof()` reports correctly. Note that the source might have more
    data in it, but it should be read via the original source reader.
    """

    source: StreamReader
    overflow: bytes

    def __init__(self, source: StreamReader):
        super().__init__()
        self.source = source
        self.overflow = b""

    @abstractmethod
    async def decode(self) -> bytes | None:
        """Read a chunk of data off the buffer and return the decoded result,
        or `None` once the coding has permanently finished.

        Subclasses must implement this method using an encoding-specific method
        to read data from `source`. Some encoding methods have chunking methods
        so this lets subclasses decide exactly how to read data off the wire.
        """
        ...

    @override
    async def read(self, n: int = -1) -> bytes:
        """Read up to `n` bytes, decoded.

        A single `decode()` step can produce more than `n` bytes (retaining the
        excess to `self.overflow`), or fewer (returned directly).
        """
        if n == 0:
            return b""

        data, self.overflow = self.overflow, b""

        if n < 0:
            while (step := await self.decode()) is not None:
                data += step
            if not self.overflow and not self.at_eof():
                self.feed_eof()
            return data

        while len(data) < n:
            step = await self.decode()
            if step is None:
                if not self.overflow and not self.at_eof():
                    self.feed_eof()
                return data
            data += step

        data, self.overflow = data[:n], data[n:]
        return data

    @override
    async def readline(self) -> bytes:
        """Read a chunk of decoded data until newline is found."""
        try:
            return await self.readuntil(b"\n")
        except IncompleteReadError as error:
            return error.partial

    @override
    async def readuntil(self, separator: ReadableBuffer | tuple[ReadableBuffer, ...] = b"\n") -> bytes:
        """Read decoded data until `separator` is found."""
        separators = separator if isinstance(separator, tuple) else (separator,)
        data, self.overflow = self.overflow, b""

        while True:
            ends = [idx + len(bytes(sep)) for sep in separators if (idx := data.find(bytes(sep))) != -1]
            if ends:
                break
            step = await self.decode()
            if step is None:
                if not self.overflow and not self.at_eof():
                    self.feed_eof()
                raise IncompleteReadError(data, None)
            data += step

        cut = min(ends)
        data, self.overflow = data[:cut], data[cut:]
        return data

    @override
    async def readexactly(self, n: int) -> bytes:
        """Read exactly `n` decoded bytes."""
        if n == 0:
            return b""

        data, self.overflow = self.overflow, b""

        while len(data) < n:
            step = await self.decode()
            if step is None:
                if not self.overflow and not self.at_eof():
                    self.feed_eof()
                raise IncompleteReadError(data, n)
            data += step

        data, self.overflow = data[:n], data[n:]
        return data


class ChunkEncodedReader(EncodedReader):
    """Decodes a stream with a chunked body encoded according to RFC 9112 §7.1.
    Stops at the terminating zero-length chunk, leaving any remaining data unread.

    Once the terminator chunk has been seen, `self.at_eof()` becomes true
    before `decode()` can be called again - every read method on
    `EncodedReader` calls `self.feed_eof()` immediately once `decode()`
    reports `None`, before returning control to whatever called it - so
    `decode()` checks that instead of touching `source` again, since
    what's sitting there next is the trailer section, not another chunk
    to parse.
    """

    CRLF_BYTES: Final = b"\r\n"

    @override
    async def decode(self) -> bytes | None:
        if self.at_eof():
            return None

        size_line = await self.source.readuntil(self.CRLF_BYTES)
        size_str = size_line[: -len(self.CRLF_BYTES)].split(b";", 1)[0]
        size = int(size_str, 16)

        if size == 0:
            return None

        data = await self.source.readexactly(size)
        await self.source.readexactly(len(self.CRLF_BYTES))
        return data


class ZlibEncodedReader(EncodedReader):
    """Shared base for the `zlib`-backed content-codings (`deflate`,
    `gzip`) - both are DEFLATE under a different wrapper, which `zlib`
    tells apart via `wbits`.

    A compressed stream can be several concatenated members (RFC 1952
    permits this for `gzip`, e.g. `cat a.gz b.gz > combined.gz`) - `zlib`
    surfaces the end of one member via `self.decompressor.eof`, with any
    trailing bytes already read left in `self.decompressor.unused_data`.
    `decode()` starts a fresh decompressor and keeps going whenever that
    happens, the same way `gzip.decompress()` does, so a multi-member
    stream still decodes to one continuous result. It only reports done
    (`None`) once `source` itself has nothing left to read - unlike
    `ChunkEncodedReader`, re-reading an exhausted `source` is always
    safe, so there's no need to remember that fact separately.

    Each `decode()` step reads at most `self.chunk_size` raw bytes from
    `source` - this has no relationship to what a caller's `read(n)`
    actually asked for (there's no way to know how many compressed bytes
    are needed to produce a given amount of decompressed output ahead of
    time), it's just a batch size. Defaults to `BODY_CHUNK_SIZE`, and can
    be set to something else via the constructor.
    """

    wbits: int
    BODY_CHUNK_SIZE: Final = 65536

    def __init__(self, source: StreamReader, chunk_size: int = BODY_CHUNK_SIZE):
        self.decompressor = zlib.decompressobj(self.wbits)
        self.chunk_size = chunk_size
        super().__init__(source)

    def decompress(self, chunk: bytes) -> bytes:
        """Decompresses one chunk of raw bytes via `self.decompressor` -
        overridden by `DeflateEncodedReader` to add its raw-DEFLATE
        fallback.
        """
        return self.decompressor.decompress(chunk)

    @override
    async def decode(self) -> bytes | None:
        chunk = await self.source.read(self.chunk_size)
        if not chunk:
            return None

        data = self.decompress(chunk)
        while self.decompressor.eof and self.decompressor.unused_data:
            leftover = self.decompressor.unused_data
            self.decompressor = zlib.decompressobj(self.wbits)
            data += self.decompress(leftover)
        return data


class GzipEncodedReader(ZlibEncodedReader):
    """Decodes `gzip`-encoded data, per RFC 1952."""

    wbits = zlib.MAX_WBITS | 16


class DeflateEncodedReader(ZlibEncodedReader):
    """Decodes `deflate`-encoded content, nominally zlib-wrapped DEFLATE
    (per RFC 1950), the format actually registered for `deflate`. Some senders
    emit raw DEFLATE (RFC 1951, no zlib header) instead so this falls back to
    raw DEFLATE the first time the zlib wrapper fails to parse.
    """

    wbits = zlib.MAX_WBITS

    @override
    def decompress(self, chunk: bytes) -> bytes:
        try:
            return self.decompressor.decompress(chunk)
        except zlib.error:
            self.decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
            return self.decompressor.decompress(chunk)
