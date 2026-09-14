import asyncio
from contextlib import closing
from ipaddress import IPv4Address

import pytest

from gossip.asyncio.protocol.multicast import MulticastDatagramProtocol
from gossip.asyncio.protocol.reply import DatagramReplyProtocol

from ...support.network import await_reply, real_interface_address

LOOPBACK = IPv4Address("127.0.0.1")
MULTICAST_GROUP = IPv4Address("239.255.255.250")


class TestMulticastDatagramProtocolConnectionMade:
    """`MulticastDatagramProtocol.connection_made()` optionally joins a
    multicast group when constructed with a `group_address`."""

    async def test_no_group_address_never_joins(self):
        """With no `group_address`, no multicast join is attempted at
        all - the socket works as a plain unicast one."""
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(MulticastDatagramProtocol, local_addr=(str(LOOPBACK), 0))
        with closing(transport):
            assert protocol.group_address is None

    async def test_joins_filtered_to_a_specific_interface(self):
        """With both `group_address` and `interface_address`, a real
        peer bound to that interface receives what's sent to the
        group."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")

        loop = asyncio.get_running_loop()
        listen_transport, listener = await loop.create_datagram_endpoint(
            lambda: DatagramReplyProtocol(loop, str(MULTICAST_GROUP), str(address)),
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
                data, _ = await await_reply(listener)
                assert data == b"ping"

    async def test_joins_without_an_interface_address_using_inaddr_any(self):
        """With `group_address` but no `interface_address`, the join
        isn't filtered to any specific interface (`INADDR_ANY`) - a
        real peer still receives what's sent to the group."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")

        loop = asyncio.get_running_loop()
        listen_transport, listener = await loop.create_datagram_endpoint(
            lambda: DatagramReplyProtocol(loop, str(MULTICAST_GROUP)),
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
                data, _ = await await_reply(listener)
                assert data == b"ping"
