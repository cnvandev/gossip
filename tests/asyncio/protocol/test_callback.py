import asyncio
from contextlib import closing
from ipaddress import IPv4Address

import pytest

from gossip.asyncio.protocol.callback import DatagramCallbackProtocol
from gossip.network.endpoint import Endpoint

from ...support.network import real_interface_address

LOOPBACK = IPv4Address("127.0.0.1")
MULTICAST_GROUP = IPv4Address("239.255.255.250")


class TestDatagramCallbackProtocolInit:
    """Building a `DatagramCallbackProtocol`."""

    async def test_defaults_to_the_running_event_loop(self):
        """Omitting `loop` still schedules `callback` on the loop that's
        actually running, not a disconnected one."""

        async def noop(_data, _interface_address, _sender, _transport):
            pass

        protocol = DatagramCallbackProtocol(noop)
        assert protocol.loop is asyncio.get_running_loop()


class TestDatagramCallbackProtocolDatagramReceived:
    """`DatagramCallbackProtocol.datagram_received()` schedules
    `callback` with the datagram's bytes, the parsed interface address
    (if any), the sender's `Endpoint`, and the receiving transport."""

    async def test_calls_back_with_the_datagram_sender_and_transport(self):
        """A real datagram arriving calls back with its bytes, the
        sender's endpoint, and the transport it arrived on - with no
        interface address, since this isn't a multicast group join."""
        loop = asyncio.get_running_loop()
        received = loop.create_future()

        async def on_datagram(data, interface_address, sender, transport):
            received.set_result((data, interface_address, sender, transport))

        listen_transport, _ = await loop.create_datagram_endpoint(lambda: DatagramCallbackProtocol(on_datagram, loop=loop), local_addr=(str(LOOPBACK), 0))
        with closing(listen_transport):
            _, listen_port = listen_transport.get_extra_info("sockname")

            send_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with closing(send_transport):
                _, sender_port = send_transport.get_extra_info("sockname")
                send_transport.sendto(b"ping", (str(LOOPBACK), listen_port))

                data, interface_address, sender, transport = await asyncio.wait_for(received, timeout=2)
                assert data == b"ping"
                assert interface_address is None
                assert sender == Endpoint(LOOPBACK, sender_port)
                assert transport is listen_transport

    async def test_reports_the_parsed_interface_address_when_joining_a_group(self):
        """Joined to a real group on a specific interface, the callback's
        `interface_address` is that same address, already parsed."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")

        loop = asyncio.get_running_loop()
        received = loop.create_future()

        async def on_datagram(_data, interface_address, _sender, _transport):
            received.set_result(interface_address)

        listen_transport, _ = await loop.create_datagram_endpoint(
            lambda: DatagramCallbackProtocol(on_datagram, loop=loop, group_address=str(MULTICAST_GROUP), interface_address=str(address)),
            local_addr=(str(MULTICAST_GROUP), 0),
            reuse_port=True,
        )
        with closing(listen_transport):
            _, listen_port = listen_transport.get_extra_info("sockname")

            send_transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol,
                local_addr=(str(address), 0),
                remote_addr=(str(MULTICAST_GROUP), listen_port),
            )
            with closing(send_transport):
                send_transport.sendto(b"ping")
                interface_address = await asyncio.wait_for(received, timeout=2)
                assert interface_address == address
