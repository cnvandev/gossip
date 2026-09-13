"""Shared network test doubles and helpers.

Not a test module - imported by tests that need a real socket to
receive from, or a free port to bind something else to.
"""

import asyncio

from gossip.network.radio import Radio

from .asyncio import wait_closing


class SingleDatagramProtocol(asyncio.DatagramProtocol):
    """A `DatagramProtocol` whose `received` future resolves with the
    first `(data, addr)` pair it gets, so a test can listen on a real
    socket without hand-rolling a `datagram_received()` override."""

    received: "asyncio.Future[tuple[bytes, tuple[str, int]]]"

    def __init__(self):
        self.received = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.received.set_result((data, addr))


async def free_tcp_port(radio: Radio) -> int:
    """Finds a free TCP port on `radio`'s own addresses, by briefly
    binding to an ephemeral one and closing it right away.

    Not perfectly race-free (something else could grab the port before
    the real listener rebinds it), but good enough for tests."""

    async def close_immediately(_, writer):
        writer.close()

    async with wait_closing(await radio.tcp_listen(close_immediately)) as probe:
        _, port = probe.sockets[0].getsockname()
    return port
