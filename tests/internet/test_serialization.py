import gzip
import zlib
from asyncio import IncompleteReadError
from asyncio import run as run_async

import pytest

from gossip.internet.serialization.encoded import ChunkEncodedReader, DeflateEncodedReader, GzipEncodedReader
from gossip.internet.serialization.limited import LimitedReader
from gossip.network.serializer import BufferedReader


class TestChunkEncodedReader:
    """Decoding a `Transfer-Encoding: chunked` body off a `source`
    reader - chunk-size lines and per-chunk trailing CRLFs get stripped
    away, leaving just the concatenated chunk-data."""

    def test_single_chunk_is_decoded(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello"

    def test_multiple_chunks_are_concatenated(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello world"

    def test_empty_body_is_just_the_terminating_chunk(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b""

    def test_chunk_extensions_are_ignored(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5;foo=bar\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello"

    def test_reports_eof_once_terminating_chunk_is_seen(self):
        async def check() -> bool:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            await reader.read()
            return reader.at_eof()

        assert run_async(check()) is True

    def test_zero_length_read_returns_nothing(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.read(0)

        assert run_async(read_it()) == b""

    def test_reading_again_once_exhausted_returns_nothing(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            await reader.read()
            return await reader.read()

        assert run_async(read_it()) == b""

    def test_trailer_section_is_left_unread_on_source(self):
        """Once the terminating chunk is seen, whatever follows on
        `source` - a trailer section here - is left completely alone,
        for a caller to read separately."""

        async def read_trailer() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\nX-Checksum: abc123\r\n\r\n")
            reader = ChunkEncodedReader(source)
            await reader.read()
            return await source.read()

        assert run_async(read_trailer()) == b"X-Checksum: abc123\r\n\r\n"

    def test_bounded_read_pulls_only_what_it_needs(self):
        """A bounded `read(n)` only decodes as many chunks as needed to
        satisfy `n` - it doesn't eagerly drain the whole body."""

        async def read_it() -> tuple[bytes, bytes]:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            first = await reader.read(5)
            rest = await reader.read()
            return first, rest

        first, rest = run_async(read_it())
        assert first == b"hello"
        assert rest == b" world"

    def test_bounded_read_leaves_overflow_for_the_next_call(self):
        """A `read(n)` smaller than what the current chunk decodes to
        only hands back `n` bytes - the rest is held in `overflow` for
        the next call, rather than being returned early or dropped."""

        async def read_it() -> tuple[bytes, bytes]:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            first = await reader.read(2)
            rest = await reader.read()
            return first, rest

        first, rest = run_async(read_it())
        assert first == b"he"
        assert rest == b"llo"

    def test_bounded_read_returns_short_if_the_coding_ends_first(self):
        """A `read(n)` asking for more than the coding actually has left
        returns whatever's available instead of waiting or raising."""

        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.read(10)

        assert run_async(read_it()) == b"hello"


class TestEncodedReaderReadline:
    """`readline()` scans decoded content (via `ChunkEncodedReader`
    here) for a newline, pulling more via `decode()` as needed."""

    def test_reads_a_line_within_one_chunk(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"b\r\nhello\nworld\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readline()

        assert run_async(read_it()) == b"hello\n"

    def test_leftover_after_the_newline_is_returned_by_the_next_call(self):
        async def read_it() -> tuple[bytes, bytes]:
            source = BufferedReader.for_bytes(b"b\r\nhello\nworld\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            first = await reader.readline()
            rest = await reader.readline()
            return first, rest

        first, rest = run_async(read_it())
        assert first == b"hello\n"
        assert rest == b"world"

    def test_pulls_across_multiple_chunks_to_find_the_newline(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n6\r\n\nworld\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readline()

        assert run_async(read_it()) == b"hello\n"

    def test_returns_everything_if_no_newline_before_exhaustion(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readline()

        assert run_async(read_it()) == b"hello"


class TestEncodedReaderReaduntil:
    """`readuntil()` scans decoded content for `separator`, raising
    `IncompleteReadError` if the coding ends before it's found."""

    def test_reads_up_to_the_separator(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"b\r\nhello;world\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readuntil(b";")

        assert run_async(read_it()) == b"hello;"

    def test_raises_if_separator_never_turns_up(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readuntil(b";")

        with pytest.raises(IncompleteReadError) as exc_info:
            run_async(read_it())
        assert exc_info.value.partial == b"hello"

    def test_shortest_match_wins_with_multiple_separators(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"b\r\nhello;world\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readuntil((b";", b"world"))

        assert run_async(read_it()) == b"hello;"


class TestEncodedReaderReadexactly:
    """`readexactly(n)` reads exactly `n` decoded bytes, raising
    `IncompleteReadError` if the coding ends first."""

    def test_reads_exactly_n_bytes(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"b\r\nhello world\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readexactly(5)

        assert run_async(read_it()) == b"hello"

    def test_leftover_is_returned_by_the_next_call(self):
        async def read_it() -> tuple[bytes, bytes]:
            source = BufferedReader.for_bytes(b"b\r\nhello world\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            first = await reader.readexactly(5)
            rest = await reader.readexactly(6)
            return first, rest

        first, rest = run_async(read_it())
        assert first == b"hello"
        assert rest == b" world"

    def test_zero_length_read_returns_nothing(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readexactly(0)

        assert run_async(read_it()) == b""

    def test_raises_if_the_coding_ends_before_n_bytes(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            reader = ChunkEncodedReader(source)
            return await reader.readexactly(10)

        with pytest.raises(IncompleteReadError) as exc_info:
            run_async(read_it())
        assert exc_info.value.partial == b"hello"
        assert exc_info.value.expected == 10


class TestGzipEncodedReader:
    """Decoding `Content-Encoding: gzip` off a `source` reader."""

    def test_decodes_a_gzip_stream(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(gzip.compress(b"hello world"))
            reader = GzipEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello world"

    def test_decodes_a_stream_fed_in_pieces(self):
        """`source` doesn't have to hand back the whole compressed
        stream in one `read()` - decoding still works chunk by chunk."""

        async def read_it() -> bytes:
            compressed = gzip.compress(b"hello world" * 1000)
            source = BufferedReader()
            for i in range(0, len(compressed), 16):
                source.feed_data(compressed[i : i + 16])
            source.feed_eof()
            reader = GzipEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello world" * 1000

    def test_reports_eof_once_decoded(self):
        async def check() -> bool:
            source = BufferedReader.for_bytes(gzip.compress(b"hi"))
            reader = GzipEncodedReader(source)
            await reader.read()
            return reader.at_eof()

        assert run_async(check()) is True

    def test_empty_input_decodes_to_empty(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(gzip.compress(b""))
            reader = GzipEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b""

    def test_chunk_size_defaults_to_body_chunk_size(self):
        async def build() -> int:
            source = BufferedReader.for_bytes(b"")
            reader = GzipEncodedReader(source)
            return reader.chunk_size

        assert run_async(build()) == GzipEncodedReader.BODY_CHUNK_SIZE

    def test_custom_chunk_size_still_decodes_correctly(self):
        """A small `chunk_size` forces `decode()` to pull `source` in
        several small reads instead of one large one, but the result is
        the same."""

        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(gzip.compress(b"hello world"))
            reader = GzipEncodedReader(source, chunk_size=4)
            assert reader.chunk_size == 4
            return await reader.read()

        assert run_async(read_it()) == b"hello world"

    def test_truncated_stream_is_exhausted_without_the_decompressor_seeing_its_own_end(self):
        """If `source` runs dry before the compressed stream's own
        end-of-data marker is seen (a truncated body), decoding just
        stops - it isn't treated as an error here."""

        async def read_it() -> bytes:
            truncated = gzip.compress(b"hello world")[:5]
            source = BufferedReader.for_bytes(truncated)
            reader = GzipEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b""

    def test_concatenated_members_decode_as_one_continuous_stream(self):
        """A `gzip` stream can be several concatenated members (RFC 1952
        permits this, e.g. `cat a.gz b.gz > combined.gz`) - decoding
        continues across the boundary instead of stopping at the first
        member's own end-of-data marker, matching `gzip.decompress()`."""

        async def read_it() -> bytes:
            combined = gzip.compress(b"hello ") + gzip.compress(b"world")
            source = BufferedReader.for_bytes(combined)
            reader = GzipEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello world"

    def test_many_concatenated_members_in_a_single_source_read(self):
        """Multiple member boundaries within one `source.read()` chunk
        are all walked, not just the first."""

        async def read_it() -> bytes:
            combined = gzip.compress(b"a") + gzip.compress(b"b") + gzip.compress(b"c")
            source = BufferedReader.for_bytes(combined)
            reader = GzipEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"abc"


class TestDeflateEncodedReader:
    """Decoding `Content-Encoding: deflate` off a `source` reader - both
    the registered zlib-wrapped form and the raw-DEFLATE form some
    senders actually use."""

    def test_decodes_a_zlib_wrapped_stream(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(zlib.compress(b"hello world"))
            reader = DeflateEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello world"

    def test_decodes_a_raw_deflate_stream(self):
        async def read_it() -> bytes:
            compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            raw = compressor.compress(b"hello world") + compressor.flush()
            source = BufferedReader.for_bytes(raw)
            reader = DeflateEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b"hello world"

    def test_reports_eof_once_decoded(self):
        async def check() -> bool:
            source = BufferedReader.for_bytes(zlib.compress(b"hi"))
            reader = DeflateEncodedReader(source)
            await reader.read()
            return reader.at_eof()

        assert run_async(check()) is True

    def test_truncated_stream_is_exhausted_without_the_decompressor_seeing_its_own_end(self):
        async def read_it() -> bytes:
            truncated = zlib.compress(b"hello world")[:2]
            source = BufferedReader.for_bytes(truncated)
            reader = DeflateEncodedReader(source)
            return await reader.read()

        assert run_async(read_it()) == b""


class TestLimitedReader:
    """Reading at most `limit` bytes off a `source` reader, regardless of
    how much more `source` actually has - modeling a `Content-Length`
    bound."""

    def test_reads_up_to_the_limit(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello world")
            reader = LimitedReader(source, 5)
            return await reader.read()

        assert run_async(read_it()) == b"hello"

    def test_does_not_read_past_the_limit(self):
        """The rest of `source`, beyond `limit`, is left completely
        unread - as if it belonged to whatever comes next on the
        connection."""

        async def read_rest() -> bytes:
            source = BufferedReader.for_bytes(b"hello world")
            reader = LimitedReader(source, 5)
            await reader.read()
            return await source.read()

        assert run_async(read_rest()) == b" world"

    def test_reports_eof_once_the_limit_is_reached(self):
        async def check() -> bool:
            source = BufferedReader.for_bytes(b"hello world")
            reader = LimitedReader(source, 5)
            await reader.read()
            return reader.at_eof()

        assert run_async(check()) is True

    def test_zero_limit_reads_nothing_and_is_immediately_eof(self):
        async def check() -> tuple[bytes, bool]:
            source = BufferedReader.for_bytes(b"hello")
            reader = LimitedReader(source, 0)
            data = await reader.read()
            return data, reader.at_eof()

        data, eof = run_async(check())
        assert data == b""
        assert eof is True

    def test_bounded_read_pulls_only_what_it_needs(self):
        async def read_it() -> tuple[bytes, bytes]:
            source = BufferedReader.for_bytes(b"hello world")
            reader = LimitedReader(source, 11)
            first = await reader.read(5)
            rest = await reader.read()
            return first, rest

        first, rest = run_async(read_it())
        assert first == b"hello"
        assert rest == b" world"

    def test_source_ending_early_raises_eof_error(self):
        """A single `read()` call only ever makes a single `source.read()`
        call, so a short `source` hands back its partial data first (like
        any stream's normal partial-read behavior) - the shortfall only
        becomes an error once a later call finds nothing left at all."""

        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hi")
            reader = LimitedReader(source, 10)
            first = await reader.read()
            assert first == b"hi"
            return await reader.read()

        with pytest.raises(EOFError):
            run_async(read_it())


class TestLimitedReaderReadline:
    """`readline()` delegates to `source.readline()`, truncating the
    result down to `limit` if it overshoots."""

    def test_reads_a_line_within_the_limit(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello\nworld\n")
            reader = LimitedReader(source, 100)
            return await reader.readline()

        assert run_async(read_it()) == b"hello\n"

    def test_truncates_a_line_that_overshoots_the_limit(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello world\n")
            reader = LimitedReader(source, 5)
            return await reader.readline()

        assert run_async(read_it()) == b"hello"

    def test_reports_eof_once_the_limit_is_reached_by_truncation(self):
        async def check() -> bool:
            source = BufferedReader.for_bytes(b"hello world\n")
            reader = LimitedReader(source, 5)
            await reader.readline()
            return reader.at_eof()

        assert run_async(check()) is True

    def test_returns_nothing_once_the_limit_is_already_reached(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello\n")
            reader = LimitedReader(source, 0)
            return await reader.readline()

        assert run_async(read_it()) == b""


class TestLimitedReaderReaduntil:
    """`readuntil()` delegates to `source.readuntil()`, raising
    `IncompleteReadError` if the separator only turns up beyond `limit`."""

    def test_reads_up_to_the_separator_within_the_limit(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello;world;")
            reader = LimitedReader(source, 100)
            return await reader.readuntil(b";")

        assert run_async(read_it()) == b"hello;"

    def test_raises_if_the_separator_is_beyond_the_limit(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello world;")
            reader = LimitedReader(source, 5)
            return await reader.readuntil(b";")

        with pytest.raises(IncompleteReadError) as exc_info:
            run_async(read_it())
        assert exc_info.value.partial == b"hello"

    def test_raises_immediately_once_the_limit_is_already_reached(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello;")
            reader = LimitedReader(source, 0)
            return await reader.readuntil(b";")

        with pytest.raises(IncompleteReadError) as exc_info:
            run_async(read_it())
        assert exc_info.value.partial == b""


class TestLimitedReaderReadexactly:
    """`readexactly(n)` caps its request to `source` the same way
    `read(n)` does, raising `IncompleteReadError` if `n` itself exceeds
    what's left of `limit`."""

    def test_reads_exactly_n_within_the_limit(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello world")
            reader = LimitedReader(source, 100)
            return await reader.readexactly(5)

        assert run_async(read_it()) == b"hello"

    def test_raises_if_n_exceeds_the_limit(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello world")
            reader = LimitedReader(source, 5)
            return await reader.readexactly(10)

        with pytest.raises(IncompleteReadError) as exc_info:
            run_async(read_it())
        assert exc_info.value.partial == b"hello"
        assert exc_info.value.expected == 10

    def test_reports_eof_once_the_limit_is_reached(self):
        async def check() -> bool:
            source = BufferedReader.for_bytes(b"hello world")
            reader = LimitedReader(source, 5)
            await reader.readexactly(5)
            return reader.at_eof()

        assert run_async(check()) is True

    def test_zero_length_read_succeeds_even_once_limit_is_reached(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello")
            reader = LimitedReader(source, 0)
            return await reader.readexactly(0)

        assert run_async(read_it()) == b""

    def test_raises_without_touching_source_once_limit_is_already_reached(self):
        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello")
            reader = LimitedReader(source, 0)
            return await reader.readexactly(3)

        with pytest.raises(IncompleteReadError) as exc_info:
            run_async(read_it())
        assert exc_info.value.partial == b""
        assert exc_info.value.expected == 3
