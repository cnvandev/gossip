import gzip
import zlib
from asyncio import IncompleteReadError

import pytest

from gossip.internet.serialization.encoded import ChunkEncodedReader, DeflateEncodedReader, GzipEncodedReader
from gossip.internet.serialization.limited import LimitedReader
from gossip.network.serializer import BufferedReader


class TestChunkEncodedReader:
    """Decoding a `Transfer-Encoding: chunked` body off a `source`
    reader - chunk-size lines and per-chunk trailing CRLFs get stripped
    away, leaving just the concatenated chunk-data."""

    async def test_single_chunk_is_decoded(self):
        """A single chunk decodes to its data."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.read() == b"hello"

    async def test_multiple_chunks_are_concatenated(self):
        """Multiple chunks decode to their concatenated data."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.read() == b"hello world"

    async def test_empty_body_is_just_the_terminating_chunk(self):
        """Just the terminating chunk decodes to an empty body."""
        source = BufferedReader.for_bytes(b"0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.read() == b""

    async def test_chunk_extensions_are_ignored(self):
        """Chunk extensions (after `;`) are ignored."""
        source = BufferedReader.for_bytes(b"5;foo=bar\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.read() == b"hello"

    async def test_reports_eof_once_terminating_chunk_is_seen(self):
        """Reports EOF once the terminating chunk is seen."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        await reader.read()
        assert reader.at_eof() is True

    async def test_zero_length_read_returns_nothing(self):
        """A zero-length read returns nothing."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.read(0) == b""

    async def test_reading_again_once_exhausted_returns_nothing(self):
        """Reading again once exhausted returns nothing."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        await reader.read()
        assert await reader.read() == b""

    async def test_trailer_section_is_left_unread_on_source(self):
        """Whatever follows the terminating chunk is left unread on `source`."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\nX-Checksum: abc123\r\n\r\n")
        reader = ChunkEncodedReader(source)
        await reader.read()
        assert await source.read() == b"X-Checksum: abc123\r\n\r\n"

    async def test_bounded_read_pulls_only_what_it_needs(self):
        """A bounded `read(n)` only decodes as many chunks as `n` needs."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        first = await reader.read(5)
        rest = await reader.read()
        assert first == b"hello"
        assert rest == b" world"

    async def test_bounded_read_leaves_overflow_for_the_next_call(self):
        """Extra decoded bytes beyond `n` are held for the next call."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        first = await reader.read(2)
        rest = await reader.read()
        assert first == b"he"
        assert rest == b"llo"

    async def test_bounded_read_returns_short_if_the_coding_ends_first(self):
        """A `read(n)` asking for more than's left returns what's available."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.read(10) == b"hello"


class TestEncodedReaderReadline:
    """`EncodedReader.readline()` scans decoded content (via `ChunkEncodedReader`
    here) for a newline, pulling more via `decode()` as needed."""

    async def test_reads_a_line_within_one_chunk(self):
        """A line within one chunk reads up to and including the newline."""
        source = BufferedReader.for_bytes(b"b\r\nhello\nworld\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.readline() == b"hello\n"

    async def test_leftover_after_the_newline_is_returned_by_the_next_call(self):
        """Content after the newline is returned by the next call."""
        source = BufferedReader.for_bytes(b"b\r\nhello\nworld\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        first = await reader.readline()
        rest = await reader.readline()
        assert first == b"hello\n"
        assert rest == b"world"

    async def test_pulls_across_multiple_chunks_to_find_the_newline(self):
        """Pulls across multiple chunks to find the newline."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n6\r\n\nworld\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.readline() == b"hello\n"

    async def test_returns_everything_if_no_newline_before_exhaustion(self):
        """With no newline before exhaustion, returns everything decoded."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.readline() == b"hello"


class TestEncodedReaderReaduntil:
    """`EncodedReader.readuntil()` scans decoded content for `separator`, raising
    `IncompleteReadError` if the coding ends before it's found."""

    async def test_reads_up_to_the_separator(self):
        """Reads up to and including the separator."""
        source = BufferedReader.for_bytes(b"b\r\nhello;world\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.readuntil(b";") == b"hello;"

    async def test_raises_if_separator_never_turns_up(self):
        """Raises `IncompleteReadError` if the separator never turns up."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        with pytest.raises(IncompleteReadError) as exc_info:
            await reader.readuntil(b";")
        assert exc_info.value.partial == b"hello"

    async def test_shortest_match_wins_with_multiple_separators(self):
        """With multiple separators, the shortest match wins."""
        source = BufferedReader.for_bytes(b"b\r\nhello;world\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.readuntil((b";", b"world")) == b"hello;"


class TestEncodedReaderReadexactly:
    """`EncodedReader.readexactly(n)` reads exactly `n` decoded bytes, raising
    `IncompleteReadError` if the coding ends first."""

    async def test_reads_exactly_n_bytes(self):
        """Reads exactly `n` decoded bytes."""
        source = BufferedReader.for_bytes(b"b\r\nhello world\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.readexactly(5) == b"hello"

    async def test_leftover_is_returned_by_the_next_call(self):
        """Leftover decoded bytes are returned by the next call."""
        source = BufferedReader.for_bytes(b"b\r\nhello world\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        first = await reader.readexactly(5)
        rest = await reader.readexactly(6)
        assert first == b"hello"
        assert rest == b" world"

    async def test_zero_length_read_returns_nothing(self):
        """A zero-length read returns nothing."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        assert await reader.readexactly(0) == b""

    async def test_raises_if_the_coding_ends_before_n_bytes(self):
        """Raises `IncompleteReadError` if the coding ends before `n` bytes."""
        source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
        reader = ChunkEncodedReader(source)
        with pytest.raises(IncompleteReadError) as exc_info:
            await reader.readexactly(10)
        assert exc_info.value.partial == b"hello"
        assert exc_info.value.expected == 10


class TestGzipEncodedReader:
    """Decoding `Content-Encoding: gzip` off a `source` reader."""

    async def test_decodes_a_gzip_stream(self):
        """A gzip stream decodes to its original content."""
        source = BufferedReader.for_bytes(gzip.compress(b"hello world"))
        reader = GzipEncodedReader(source)
        assert await reader.read() == b"hello world"

    async def test_decodes_a_stream_fed_in_pieces(self):
        """Decoding works even when `source` hands back small pieces."""
        compressed = gzip.compress(b"hello world" * 1000)
        source = BufferedReader()
        for i in range(0, len(compressed), 16):
            source.feed_data(compressed[i : i + 16])
        source.feed_eof()
        reader = GzipEncodedReader(source)
        assert await reader.read() == b"hello world" * 1000

    async def test_reports_eof_once_decoded(self):
        """Reports EOF once fully decoded."""
        source = BufferedReader.for_bytes(gzip.compress(b"hi"))
        reader = GzipEncodedReader(source)
        await reader.read()
        assert reader.at_eof() is True

    async def test_empty_input_decodes_to_empty(self):
        """An empty gzip stream decodes to empty."""
        source = BufferedReader.for_bytes(gzip.compress(b""))
        reader = GzipEncodedReader(source)
        assert await reader.read() == b""

    async def test_chunk_size_defaults_to_body_chunk_size(self):
        """`chunk_size` defaults to `BODY_CHUNK_SIZE`."""
        source = BufferedReader.for_bytes(b"")
        reader = GzipEncodedReader(source)
        assert reader.chunk_size == GzipEncodedReader.BODY_CHUNK_SIZE

    async def test_custom_chunk_size_still_decodes_correctly(self):
        """A small `chunk_size` still decodes to the same result."""
        source = BufferedReader.for_bytes(gzip.compress(b"hello world"))
        reader = GzipEncodedReader(source, chunk_size=4)
        assert reader.chunk_size == 4
        assert await reader.read() == b"hello world"

    async def test_truncated_stream_is_exhausted_without_the_decompressor_seeing_its_own_end(self):
        """A truncated stream just stops decoding, rather than raising."""
        truncated = gzip.compress(b"hello world")[:5]
        source = BufferedReader.for_bytes(truncated)
        reader = GzipEncodedReader(source)
        assert await reader.read() == b""

    async def test_concatenated_members_decode_as_one_continuous_stream(self):
        """Concatenated gzip members decode as one continuous stream."""
        combined = gzip.compress(b"hello ") + gzip.compress(b"world")
        source = BufferedReader.for_bytes(combined)
        reader = GzipEncodedReader(source)
        assert await reader.read() == b"hello world"

    async def test_many_concatenated_members_in_a_single_source_read(self):
        """Multiple member boundaries within one chunk are all walked."""
        combined = gzip.compress(b"a") + gzip.compress(b"b") + gzip.compress(b"c")
        source = BufferedReader.for_bytes(combined)
        reader = GzipEncodedReader(source)
        assert await reader.read() == b"abc"


class TestDeflateEncodedReader:
    """Decoding `Content-Encoding: deflate` off a `source` reader - both
    the registered zlib-wrapped form and the raw-DEFLATE form some
    senders actually use."""

    async def test_decodes_a_zlib_wrapped_stream(self):
        """A zlib-wrapped stream decodes to its original content."""
        source = BufferedReader.for_bytes(zlib.compress(b"hello world"))
        reader = DeflateEncodedReader(source)
        assert await reader.read() == b"hello world"

    async def test_decodes_a_raw_deflate_stream(self):
        """A raw (unwrapped) DEFLATE stream decodes to its original content."""
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        raw = compressor.compress(b"hello world") + compressor.flush()
        source = BufferedReader.for_bytes(raw)
        reader = DeflateEncodedReader(source)
        assert await reader.read() == b"hello world"

    async def test_reports_eof_once_decoded(self):
        """Reports EOF once fully decoded."""
        source = BufferedReader.for_bytes(zlib.compress(b"hi"))
        reader = DeflateEncodedReader(source)
        await reader.read()
        assert reader.at_eof() is True

    async def test_truncated_stream_is_exhausted_without_the_decompressor_seeing_its_own_end(self):
        """A truncated stream just stops decoding, rather than raising."""
        truncated = zlib.compress(b"hello world")[:2]
        source = BufferedReader.for_bytes(truncated)
        reader = DeflateEncodedReader(source)
        assert await reader.read() == b""


class TestLimitedReader:
    """Reading at most `limit` bytes off a `source` reader, regardless of
    how much more `source` actually has - modeling a `Content-Length`
    bound."""

    async def test_reads_up_to_the_limit(self):
        """Reads up to `limit` bytes."""
        source = BufferedReader.for_bytes(b"hello world")
        reader = LimitedReader(source, 5)
        assert await reader.read() == b"hello"

    async def test_does_not_read_past_the_limit(self):
        """Bytes beyond `limit` are left unread on `source`."""
        source = BufferedReader.for_bytes(b"hello world")
        reader = LimitedReader(source, 5)
        await reader.read()
        assert await source.read() == b" world"

    async def test_reports_eof_once_the_limit_is_reached(self):
        """Reports EOF once `limit` is reached."""
        source = BufferedReader.for_bytes(b"hello world")
        reader = LimitedReader(source, 5)
        await reader.read()
        assert reader.at_eof() is True

    async def test_zero_limit_reads_nothing_and_is_immediately_eof(self):
        """A zero limit reads nothing and is immediately EOF."""
        source = BufferedReader.for_bytes(b"hello")
        reader = LimitedReader(source, 0)
        data = await reader.read()
        assert data == b""
        assert reader.at_eof() is True

    async def test_bounded_read_pulls_only_what_it_needs(self):
        """A bounded `read(n)` only pulls what `n` needs."""
        source = BufferedReader.for_bytes(b"hello world")
        reader = LimitedReader(source, 11)
        first = await reader.read(5)
        rest = await reader.read()
        assert first == b"hello"
        assert rest == b" world"

    async def test_source_ending_early_raises_eof_error(self):
        """A `source` that ends before `limit` raises only once a later
        call finds nothing left at all."""
        source = BufferedReader.for_bytes(b"hi")
        reader = LimitedReader(source, 10)
        first = await reader.read()
        assert first == b"hi"
        with pytest.raises(EOFError):
            await reader.read()


class TestLimitedReaderReadline:
    """`LimitedReader.readline()` delegates to `source.readline()`, truncating the
    result down to `limit` if it overshoots."""

    async def test_reads_a_line_within_the_limit(self):
        """A line within the limit reads up to and including the newline."""
        source = BufferedReader.for_bytes(b"hello\nworld\n")
        reader = LimitedReader(source, 100)
        assert await reader.readline() == b"hello\n"

    async def test_truncates_a_line_that_overshoots_the_limit(self):
        """A line that overshoots the limit is truncated to it."""
        source = BufferedReader.for_bytes(b"hello world\n")
        reader = LimitedReader(source, 5)
        assert await reader.readline() == b"hello"

    async def test_reports_eof_once_the_limit_is_reached_by_truncation(self):
        """Reports EOF once the limit is reached by truncation."""
        source = BufferedReader.for_bytes(b"hello world\n")
        reader = LimitedReader(source, 5)
        await reader.readline()
        assert reader.at_eof() is True

    async def test_returns_nothing_once_the_limit_is_already_reached(self):
        """Returns nothing once the limit is already reached."""
        source = BufferedReader.for_bytes(b"hello\n")
        reader = LimitedReader(source, 0)
        assert await reader.readline() == b""


class TestLimitedReaderReaduntil:
    """`LimitedReader.readuntil()` delegates to `source.readuntil()`, raising
    `IncompleteReadError` if the separator only turns up beyond `limit`."""

    async def test_reads_up_to_the_separator_within_the_limit(self):
        """Reads up to the separator when it's within the limit."""
        source = BufferedReader.for_bytes(b"hello;world;")
        reader = LimitedReader(source, 100)
        assert await reader.readuntil(b";") == b"hello;"

    async def test_raises_if_the_separator_is_beyond_the_limit(self):
        """Raises `IncompleteReadError` if the separator is beyond the limit."""
        source = BufferedReader.for_bytes(b"hello world;")
        reader = LimitedReader(source, 5)
        with pytest.raises(IncompleteReadError) as exc_info:
            await reader.readuntil(b";")
        assert exc_info.value.partial == b"hello"

    async def test_raises_immediately_once_the_limit_is_already_reached(self):
        """Raises immediately once the limit is already reached."""
        source = BufferedReader.for_bytes(b"hello;")
        reader = LimitedReader(source, 0)
        with pytest.raises(IncompleteReadError) as exc_info:
            await reader.readuntil(b";")
        assert exc_info.value.partial == b""


class TestLimitedReaderReadexactly:
    """`LimitedReader.readexactly(n)` caps its request to `source` the same way
    `read(n)` does, raising `IncompleteReadError` if `n` itself exceeds
    what's left of `limit`."""

    async def test_reads_exactly_n_within_the_limit(self):
        """Reads exactly `n` bytes when within the limit."""
        source = BufferedReader.for_bytes(b"hello world")
        reader = LimitedReader(source, 100)
        assert await reader.readexactly(5) == b"hello"

    async def test_raises_if_n_exceeds_the_limit(self):
        """Raises `IncompleteReadError` if `n` exceeds the limit."""
        source = BufferedReader.for_bytes(b"hello world")
        reader = LimitedReader(source, 5)
        with pytest.raises(IncompleteReadError) as exc_info:
            await reader.readexactly(10)
        assert exc_info.value.partial == b"hello"
        assert exc_info.value.expected == 10

    async def test_reports_eof_once_the_limit_is_reached(self):
        """Reports EOF once the limit is reached."""
        source = BufferedReader.for_bytes(b"hello world")
        reader = LimitedReader(source, 5)
        await reader.readexactly(5)
        assert reader.at_eof() is True

    async def test_zero_length_read_succeeds_even_once_limit_is_reached(self):
        """A zero-length read succeeds even once the limit is reached."""
        source = BufferedReader.for_bytes(b"hello")
        reader = LimitedReader(source, 0)
        assert await reader.readexactly(0) == b""

    async def test_raises_without_touching_source_once_limit_is_already_reached(self):
        """Raises without touching `source` once the limit is already reached."""
        source = BufferedReader.for_bytes(b"hello")
        reader = LimitedReader(source, 0)
        with pytest.raises(IncompleteReadError) as exc_info:
            await reader.readexactly(3)
        assert exc_info.value.partial == b""
        assert exc_info.value.expected == 3
