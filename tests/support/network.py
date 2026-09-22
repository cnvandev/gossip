"""Shared network test doubles and helpers.

Not a test module - imported by tests that need a real socket to
receive from, or a free port to bind something else to.
"""

import asyncio
from asyncio.streams import StreamReader, StreamWriter
from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import Self

import netifaces
from netifaces import AF_INET

from gossip.asyncio.protocol.reply import DatagramReplyProtocol
from gossip.http.message import HTTPRequest
from gossip.network.endpoint import Endpoint
from gossip.network.radio import Radio

from .asyncio import MessageCollector, wait_closing

LOOPBACK = IPv4Address("127.0.0.1")


@dataclass(frozen=True)
class RawMessage:
    """A minimal `Serializable` that carries raw bytes verbatim - lets a
    test dogfood `Replier` for a round trip without needing any real
    message framing."""

    data: bytes

    def __bytes__(self) -> bytes:
        return self.data

    async def write_to(self, writer: StreamWriter) -> None:
        writer.write(self.data)
        await writer.drain()

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None:
        if isinstance(reader, tuple):
            data, _ = reader
        else:
            data = await reader.read()
        return cls(data) if data else None


async def echo_datagram(prompt: RawMessage, _remote: Endpoint, _local: Endpoint) -> tuple[RawMessage]:
    """A `Replier` callback that echoes a raw datagram straight back to
    whoever sent it."""
    return (prompt,)


async def await_reply(protocol: DatagramReplyProtocol, timeout: float = 2) -> tuple[bytes, Endpoint]:
    """Waits for a `DatagramReplyProtocol`'s `reply` future, asserting
    it actually got a datagram rather than closing with none."""
    reply = await asyncio.wait_for(protocol.reply, timeout=timeout)
    assert reply is not None
    return reply


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


async def free_udp_port(radio: Radio) -> int:
    """Finds a free UDP port on `radio`'s own addresses, by briefly
    binding to an ephemeral one and closing it right away.

    Not perfectly race-free (something else could grab the port before
    the real listener rebinds it), but good enough for tests."""

    async def noop(_data, _interface_address, _sender, _transport):
        pass

    (probe, _), = await radio.udp_listen(noop, port=0)
    _, port = probe.get_extra_info("sockname")
    probe.close()
    return port


async def collect_notifications(expected: int, port: int) -> list[HTTPRequest]:
    """Listens on loopback at `port` for `expected` datagrams sent via
    `Radio.loopback()` - whose default, broadcast-less binding sends
    straight to its own address rather than a real multicast group -
    returning them deserialized once they've all arrived."""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: MessageCollector(HTTPRequest.read_from, expected), local_addr=(str(LOOPBACK), port), reuse_port=True,
    )
    try:
        await asyncio.wait_for(protocol.done, timeout=2)
        return protocol.messages
    finally:
        transport.close()


class NotifyRecorder:
    """A `Replier` callback that records every request it's given, in
    order, and never sends back a reply of its own."""

    def __init__(self):
        self.received: list[HTTPRequest] = []

    async def __call__(self, request: HTTPRequest, remote: Endpoint, local: Endpoint) -> tuple[()]:
        self.received.append(request)
        return ()


def real_interface_address() -> IPv4Address | None:
    """The first real, non-loopback IPv4 address `netifaces` reports for
    this machine, or `None` if it has none.

    Multicast delivery needs a real interface - it doesn't reliably
    route back to loopback listeners."""
    for name in netifaces.interfaces():
        if name.startswith("lo"):
            continue
        for entry in netifaces.ifaddresses(name).get(AF_INET, []):
            return IPv4Address(entry["addr"])
    return None
