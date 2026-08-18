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

    def write(self, data: bytes | bytearray | memoryview) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        pass

    def __del__(self, warnings=None) -> None:
        # The real StreamWriter.__del__ checks self._transport, which we
        # never set (see __init__) - skip that check entirely.
        pass
