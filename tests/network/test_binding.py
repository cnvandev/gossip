import asyncio
from contextlib import closing
from ipaddress import IPv4Address, IPv4Network, IPv6Network

import pytest
from netifaces import AF_INET

from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface
from gossip.network.radio import Radio
from gossip.network.replier import Replier

from ..support.asyncio import wait_closing
from ..support.network import RawMessage, await_reply, echo_datagram, real_interface_address

LOOPBACK = IPv4Address("127.0.0.1")


class TestBindingAddress:
    """`Binding.address` is just an alias for its own `addr` field."""

    def test_returns_the_bound_addr(self):
        """`address` returns the same value as `addr`."""
        binding = Binding(LOOPBACK)
        assert binding.address == LOOPBACK


class TestBindingFromIfaddresses:
    """Building a `Binding` from a `netifaces`-style address dict."""

    def test_parses_the_address(self):
        """`addr` parses to an `IPv4Address`."""
        binding = Binding.from_ifaddresses({"addr": "127.0.0.1"})
        assert binding.addr == LOOPBACK

    def test_parses_peer_and_broadcast(self):
        """`peer` and `broadcast` parse to `IPv4Address`es too."""
        binding = Binding.from_ifaddresses({"addr": "127.0.0.1", "peer": "127.0.0.2", "broadcast": "127.255.255.255"})
        assert binding.peer == IPv4Address("127.0.0.2")
        assert binding.broadcast == IPv4Address("127.255.255.255")

    def test_missing_optional_fields_default_to_none(self):
        """Omitted `netmask`/`peer`/`broadcast` all default to `None`."""
        binding = Binding.from_ifaddresses({"addr": "127.0.0.1"})
        assert binding.netmask is None
        assert binding.peer is None
        assert binding.broadcast is None

    def test_dotted_decimal_netmask_combines_with_addr_for_the_real_prefix(self):
        """A dotted-decimal `netmask` combines with `addr` to get the real
        network prefix, rather than being parsed as a bare `/32` address."""
        binding = Binding.from_ifaddresses({"addr": "192.168.1.5", "netmask": "255.255.255.0"})
        assert binding.netmask == IPv4Network("192.168.1.0/24")

    def test_already_prefixed_netmask_is_handled_too(self):
        """An IPv6-style `netmask` (already `address/prefix`) parses to the
        same prefix length."""
        binding = Binding.from_ifaddresses({"addr": "fe80::1", "netmask": "ffff:ffff:ffff:ffff::/64"})
        assert binding.netmask == IPv6Network("fe80::/64")


class TestBindingTcp:
    """`Binding.tcp_listen()`/`Binding.tcp_connect()` round-trip real bytes
    over a real TCP socket on loopback, bound to this `Binding`'s own
    address."""

    async def test_round_trips_bytes_from_the_bindings_own_address(self):
        """A client connected via `tcp_connect()` delivers its bytes to
        whatever's listening via `tcp_listen()`, from the binding's address."""
        binding = Binding(LOOPBACK)
        received = asyncio.get_running_loop().create_future()

        async def on_connection(reader, writer):
            received.set_result(await reader.read())
            writer.close()

        server = await binding.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            _, writer = await binding.tcp_connect(Endpoint(LOOPBACK, port))
            async with wait_closing(writer):
                host, _ = writer.get_extra_info("sockname")
                assert host == str(LOOPBACK)
                writer.write(b"hello")
                writer.write_eof()
                assert await asyncio.wait_for(received, timeout=2) == b"hello"

    async def test_listens_on_the_given_port_when_specified(self):
        """An explicit `port` is bound to, rather than choosing one."""
        binding = Binding(LOOPBACK)

        async def on_connection(_, writer):
            writer.close()

        async with wait_closing(await binding.tcp_listen(on_connection)) as probe:
            _, free_port = probe.sockets[0].getsockname()

        server = await binding.tcp_listen(on_connection, port=free_port)
        async with wait_closing(server):
            assert server.sockets[0].getsockname() == (str(LOOPBACK), free_port)


class TestBindingUdpSend:
    """`Binding.udp_send()` opens a UDP socket bound to this `Binding`'s
    own address, targeting the given remote endpoint."""

    async def test_sends_from_the_bindings_own_address_to_the_remote_endpoint(self):
        """The datagram arrives at the remote endpoint, sent from the
        binding's own address - a `Replier` on the other end proves it
        by echoing it straight back.

        `udp_send()`'s socket is OS-connected to the remote endpoint,
        so this only works because `Replier` replies over the same
        transport it received on, not a fresh one."""
        binding = Binding(LOOPBACK)
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))

        async with Replier(callback=echo_datagram, udp={0: RawMessage.read_from}, radio=radio) as replier:
            _, port = replier.udp_transports[0].get_extra_info("sockname")
            send_transport, sender = await binding.udp_send(Endpoint(LOOPBACK, port))
            with closing(send_transport):
                host, _ = send_transport.get_extra_info("sockname")
                assert host == str(LOOPBACK)
                send_transport.sendto(b"ping")
                data, _ = await await_reply(sender)
                assert data == b"ping"


class TestBindingUdpListen:
    """`Binding.udp_listen()` calls back with each datagram it receives,
    tagged with the sender's endpoint and the receiving transport."""

    async def test_calls_back_with_the_datagram_and_sender(self):
        """The callback receives the datagram's bytes and the sender's
        endpoint."""
        binding = Binding(LOOPBACK)
        loop = asyncio.get_running_loop()
        received = loop.create_future()

        async def on_datagram(data, _interface_address, sender, _transport):
            received.set_result((data, sender))

        listen_transport, _ = await binding.udp_listen(on_datagram, port=0)
        with closing(listen_transport):
            _, listen_port = listen_transport.get_extra_info("sockname")

            send_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with closing(send_transport):
                _, sender_port = send_transport.get_extra_info("sockname")
                send_transport.sendto(b"ping", (str(LOOPBACK), listen_port))
                data, sender = await asyncio.wait_for(received, timeout=2)
                assert data == b"ping"
                assert sender == Endpoint(LOOPBACK, sender_port)

    async def test_a_group_address_that_cant_be_routed_raises(self):
        """A `group_address` that can't actually be reached (loopback,
        typically - it isn't in the system's multicast routes unless
        one's been added for it) raises, rather than silently binding
        to a group nothing will ever be delivered to."""
        binding = Binding(LOOPBACK)
        group = IPv4Address("239.255.255.250")

        async def on_datagram(_data, _interface_address, _sender, _transport):
            pass

        with pytest.raises(ValueError):
            await binding.udp_listen(on_datagram, port=1900, group_address=group)

    async def test_a_group_address_listens_on_the_group_when_it_can_be_routed(self):
        """With a real, routable `group_address`, the socket binds to
        the group address and port, not the binding's own address."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")

        binding = Binding(address)
        group = IPv4Address("239.255.255.250")

        async def on_datagram(_data, _interface_address, _sender, _transport):
            pass

        transport, _ = await binding.udp_listen(on_datagram, port=1900, group_address=group)
        with closing(transport):
            assert transport.get_extra_info("sockname") == (str(group), 1900)


class TestBindingCanMulticastTo:
    """`Binding.can_multicast_to()` reports whether the OS would
    actually route traffic to a given multicast group out through this
    binding's own address."""

    async def test_is_false_for_loopback(self):
        """Loopback isn't in the system's multicast routes unless one's
        been added for it, so it can't reach a real group."""
        binding = Binding(LOOPBACK)
        assert await binding.can_multicast_to(IPv4Address("239.255.255.250")) is False

    async def test_is_true_for_a_real_interface(self):
        """A real, routable interface can reach a real group."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")

        binding = Binding(address)
        assert await binding.can_multicast_to(IPv4Address("239.255.255.250")) is True


class TestBindingUdpBroadcast:
    """`Binding.udp_broadcast()` targets the given group address if this
    binding supports broadcast, or falls back to its own address (to
    multicast locally) if it doesn't."""

    async def test_binds_to_the_bindings_own_address(self):
        """Regardless of `broadcast`, the socket itself is bound to the
        binding's own address."""
        binding = Binding(LOOPBACK, broadcast=LOOPBACK)
        transport, _ = await binding.udp_broadcast(LOOPBACK, port=0)
        with closing(transport):
            host, _ = transport.get_extra_info("sockname")
            assert host == str(LOOPBACK)

    async def test_with_a_broadcast_address_targets_the_group_address(self):
        """When broadcasting, the group address is reachable - a
        `Replier` bound there echoes back what's sent."""
        binding = Binding(LOOPBACK, broadcast=LOOPBACK)
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))

        async with Replier(callback=echo_datagram, udp={0: RawMessage.read_from}, radio=radio) as replier:
            _, port = replier.udp_transports[0].get_extra_info("sockname")
            transport, sender = await binding.udp_broadcast(LOOPBACK, port=port)
            with closing(transport):
                transport.sendto(b"ping")
                data, _ = await await_reply(sender)
                assert data == b"ping"

    async def test_without_a_broadcast_address_falls_back_to_its_own_address(self):
        """When not broadcasting, the datagram goes to the binding's own
        address, rather than the given group address."""
        binding = Binding(LOOPBACK, broadcast=None)
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))

        # Listens on the binding's own address - if `broadcast=None` is
        # honored, the datagram lands here rather than at `other_group`.
        async with Replier(callback=echo_datagram, udp={0: RawMessage.read_from}, radio=radio) as replier:
            _, port = replier.udp_transports[0].get_extra_info("sockname")
            other_group = IPv4Address("127.0.0.2")
            transport, sender = await binding.udp_broadcast(other_group, port=port)
            with closing(transport):
                transport.sendto(b"ping")
                data, _ = await await_reply(sender)
                assert data == b"ping"
