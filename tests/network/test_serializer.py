from asyncio import StreamReader, get_running_loop, sleep
from asyncio import run as run_async

from gossip.network.serializer import BufferedReader


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

    def test_wait_closed_blocks_until_feed_eof(self):
        """`wait_closed()` genuinely suspends until `feed_eof()` is
        called - it isn't already resolved just because the reader
        exists."""

        async def check() -> bool:
            reader = BufferedReader()
            wait_task = get_running_loop().create_task(reader.wait_closed())
            await sleep(0)
            not_yet_closed = not wait_task.done()

            reader.feed_eof()
            await wait_task
            return not_yet_closed

        assert run_async(check()) is True


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

    def test_wait_closed_returns_immediately(self):
        """`feed_eof()` already happened by construction, so `wait_closed()`
        never actually suspends."""
        reader = BufferedReader.for_bytes(b"hello")
        assert run_async(reader.wait_closed()) is None
