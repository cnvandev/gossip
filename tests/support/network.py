"""Shared network test doubles.

Not a test module - imported by tests that need a real socket to
receive from.
"""

import asyncio


class SingleDatagramProtocol(asyncio.DatagramProtocol):
    """A `DatagramProtocol` whose `received` future resolves with the
    first `(data, addr)` pair it gets, so a test can listen on a real
    socket without hand-rolling a `datagram_received()` override."""

    received: "asyncio.Future[tuple[bytes, tuple[str, int]]]"

    def __init__(self):
        self.received = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.received.set_result((data, addr))
