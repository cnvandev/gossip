"""Shared asyncio-stream test doubles.

Not a test module - imported by tests that need to exercise write_to()
without a real connection.
"""

from asyncio import StreamWriter


class FakeStreamWriter(StreamWriter):
    """A minimal stand-in for `asyncio.StreamWriter` that just accumulates
    what's written, so `write_to()` can be tested without a real
    connection.

    Subclasses the real `StreamWriter` (rather than just duck-typing it) so
    it type-checks anywhere a `StreamWriter` is expected. Deliberately
    skips `StreamWriter.__init__()` - it demands a real transport/protocol/
    reader/loop, none of which a test has lying around - so anything beyond
    `write()`/`drain()` (e.g. `close()`, `get_extra_info()`) is unsupported.
    """

    def __init__(self):
        self.buffer = bytearray()
        self.drained = False

    def write(self, data: bytes | bytearray | memoryview) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        self.drained = True

    def __del__(self, warnings=None) -> None:
        # The real StreamWriter.__del__ checks self._transport, which we
        # never set (see __init__) - skip that check entirely.
        pass


class RecordingWriter:
    """Wraps a real `StreamWriter`, delegating everything to it except
    recording whether `close()` was actually called.

    A real (if abandoned) `StreamWriter` gets closed by its own
    `__del__` once nothing references it any more - and exactly when
    that happens depends on the garbage collector, not on the code
    under test. That makes "did our code choose to close this"
    unobservable from the peer's side of the socket: an EOF might mean
    our code closed it, or might just mean the GC got there first. This
    records the deliberate `close()` call directly instead, so a test
    doesn't depend on GC timing to tell the two apart."""

    def __init__(self, writer):
        self.writer = writer
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.writer.close()

    def __getattr__(self, name):
        return getattr(self.writer, name)
