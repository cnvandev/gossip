from asyncio import StreamReader
from asyncio import run as run_async

from gossip.network.serializer import BoundedReader, BufferedReader


class TestBufferedReader:
    """`BufferedReader` - a `StreamReader` over an in-memory buffer that
    skips the real `StreamReader.__init__()`'s event-loop lookup, so it can
    be built (and fed) outside a running loop."""

    def test_works_with_no_running_event_loop(self):
        """Constructing one, and feeding it, doesn't require a running
        event loop - it has to work from a plain, synchronous constructor
        call (building a message before any `await`), not just from inside
        a coroutine.

        This is a regression test: the real `StreamReader.__init__()`
        eagerly grabs `asyncio.get_event_loop()`, which raises outside a
        running loop - that's exactly why `BufferedReader` skips it."""
        reader = BufferedReader()
        reader.feed_data(b"hi")
        reader.feed_eof()
        assert isinstance(reader, StreamReader)

    def test_yields_exactly_the_fed_bytes(self):
        """Reading it back returns exactly what was fed, then EOF."""

        async def read_it() -> bytes:
            reader = BufferedReader()
            reader.feed_data(b"hello")
            reader.feed_eof()
            return await reader.read()

        assert run_async(read_it()) == b"hello"


class TestBufferedReaderForBytes:
    """`BufferedReader.for_bytes()` - the factory that automates the
    feed/EOF pair every caller building one from a plain `bytes` object
    would otherwise repeat."""

    def test_works_with_no_running_event_loop(self):
        """Building one this way doesn't require a running event loop
        either, same as the raw constructor - it's just automating the
        `feed_data()`/`feed_eof()` calls, not introducing anything that
        would need one."""
        reader = BufferedReader.for_bytes(b"hi")
        assert isinstance(reader, StreamReader)

    def test_yields_exactly_the_given_bytes(self):
        """Reading it back returns exactly the bytes it was built from,
        then EOF."""

        async def read_it() -> bytes:
            reader = BufferedReader.for_bytes(b"hello")
            return await reader.read()

        assert run_async(read_it()) == b"hello"


class TestBoundedReader:
    """`BoundedReader` - a `StreamReader` that pumps at most `limit` bytes
    from a source reader, then reports EOF, regardless of what's left on
    the source behind it."""

    def test_stops_at_the_limit_even_though_more_is_available(self):
        """Only `limit` bytes come through, even though the source has
        more behind them."""

        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"hello world, more than five bytes")
            bounded = BoundedReader(source, 5)
            return await bounded.read()

        assert run_async(read_it()) == b"hello"

    def test_ends_early_if_the_source_does(self):
        """A source that ends before delivering `limit` bytes isn't an
        error - the bounded reader just ends up shorter than `limit`, same
        as a real connection closing early."""

        async def read_it() -> bytes:
            source = BufferedReader.for_bytes(b"short")
            bounded = BoundedReader(source, 999)
            return await bounded.read()

        assert run_async(read_it()) == b"short"

    def test_fires_on_exhausted_once_the_limit_is_reached(self):
        """The callback fires exactly once, once the limit's worth of
        bytes has been pumped through."""

        async def read_it() -> int:
            calls = 0

            def on_exhausted() -> None:
                nonlocal calls
                calls += 1

            source = BufferedReader.for_bytes(b"hello world")
            bounded = BoundedReader(source, 5, on_exhausted=on_exhausted)
            await bounded.read()
            return calls

        assert run_async(read_it()) == 1

    def test_fires_on_exhausted_even_if_the_source_ends_early(self):
        """The callback still fires exactly once when the source ends
        before the limit - "exhausted" means the pump is done, not
        specifically that the limit was reached."""

        async def read_it() -> int:
            calls = 0

            def on_exhausted() -> None:
                nonlocal calls
                calls += 1

            source = BufferedReader.for_bytes(b"short")
            bounded = BoundedReader(source, 999, on_exhausted=on_exhausted)
            await bounded.read()
            return calls

        assert run_async(read_it()) == 1

    def test_fires_on_exhausted_regardless_of_who_reads(self):
        """The pump runs as a background task independent of any
        particular caller's reads - the callback fires even if nothing
        ever calls `.read()` on the bounded reader itself, as long as the
        pump gets a chance to run."""

        async def run_it() -> int:
            calls = 0

            def on_exhausted() -> None:
                nonlocal calls
                calls += 1

            source = BufferedReader.for_bytes(b"hello")
            bounded = BoundedReader(source, 5, on_exhausted=on_exhausted)
            await bounded._pump_task
            return calls

        assert run_async(run_it()) == 1

    def test_at_eof_reflects_the_cutoff_not_the_source(self):
        """`at_eof()` follows the bounded reader's own state - once it's
        drained up to the cutoff, it reports EOF even if the underlying
        source object still has data left in it that just never got
        pumped through."""

        async def read_it() -> bool:
            source = BufferedReader.for_bytes(b"hello world")
            bounded = BoundedReader(source, 5)
            await bounded.read()
            return bounded.at_eof()

        assert run_async(read_it()) is True
