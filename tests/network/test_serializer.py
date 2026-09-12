from asyncio import StreamReader, get_running_loop, sleep
from typing import Self

from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader, Serializable

from ..support.streams import FakeStreamWriter


class Message(Serializable):
    """A trivial `Serializable` that doesn't override `write_to()`, so it
    exercises the default implementation."""

    def __init__(self, data: bytes):
        self.data = data

    def __bytes__(self) -> bytes:
        return self.data

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None:
        raise NotImplementedError("not exercised by these tests")


class TestSerializableWriteTo:
    """`Serializable.write_to()`'s default implementation - writes
    `bytes(self)` and drains."""

    async def test_writes_bytes_and_drains(self):
        """The full `bytes()` form is written and the write is drained."""
        writer = FakeStreamWriter()
        await Message(b"hello").write_to(writer)
        assert bytes(writer.buffer) == b"hello"
        assert writer.drained is True


class TestBufferedReader:
    """`BufferedReader` - a `StreamReader` over an in-memory buffer that
    skips the real `StreamReader.__init__()`'s event-loop lookup, so it can
    be built (and fed) outside a running loop."""

    def test_works_with_no_running_event_loop(self):
        """Constructing and feeding one doesn't require a running event loop."""
        reader = BufferedReader()
        reader.feed_data(b"hi")
        reader.feed_eof()
        assert isinstance(reader, StreamReader)

    async def test_yields_exactly_the_fed_bytes(self):
        """Reading it back returns exactly what was fed, then EOF."""
        reader = BufferedReader()
        reader.feed_data(b"hello")
        reader.feed_eof()
        assert await reader.read() == b"hello"

    async def test_wait_closed_blocks_until_feed_eof(self):
        """`wait_closed()` suspends until `feed_eof()` is called."""
        reader = BufferedReader()
        wait_task = get_running_loop().create_task(reader.wait_closed())
        await sleep(0)
        not_yet_closed = not wait_task.done()

        reader.feed_eof()
        await wait_task
        assert not_yet_closed is True


class TestBufferedReaderForBytes:
    """`BufferedReader.for_bytes()` - the factory that automates the
    feed/EOF pair every caller building one from a plain `bytes` object
    would otherwise repeat."""

    def test_works_with_no_running_event_loop(self):
        """Doesn't require a running event loop, same as the raw constructor."""
        reader = BufferedReader.for_bytes(b"hi")
        assert isinstance(reader, StreamReader)

    async def test_yields_exactly_the_given_bytes(self):
        """Reading it back returns exactly the bytes it was built from."""
        reader = BufferedReader.for_bytes(b"hello")
        assert await reader.read() == b"hello"

    async def test_wait_closed_returns_immediately(self):
        """Already fed and EOF'd by construction, so this never suspends."""
        reader = BufferedReader.for_bytes(b"hello")
        assert await reader.wait_closed() is None
