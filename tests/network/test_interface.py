import asyncio
from contextlib import closing
from ipaddress import IPv4Address, IPv4Network

import netifaces
from netifaces import AF_INET

from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface

from ..support.asyncio import wait_closing
from ..support.network import SingleDatagramProtocol

LOOPBACK = IPv4Address("127.0.0.1")


class TestInterfaceAddresses:
    """`Interface.addresses()` - every address bound to this interface,
    across every address family."""

    def test_returns_every_bindings_address(self):
        """Every binding's address is included, across every family."""
        interface = Interface("lo0", {AF_INET: (Binding(LOOPBACK), Binding(IPv4Address("10.0.0.1")))})
        assert set(interface.addresses()) == {LOOPBACK, IPv4Address("10.0.0.1")}

    def test_empty_bindings_yields_no_addresses(self):
        """No bindings at all yields no addresses."""
        interface = Interface("lo0", {})
        assert list(interface.addresses()) == []


class TestInterfaceTcp:
    """`Interface.tcp_listen()`/`Interface.tcp_send()` round-trip real
    bytes over loopback, on whichever addresses the interface is bound to."""

    async def test_round_trips_bytes(self):
        """A client connected via `tcp_send()` delivers its bytes to
        whatever's listening via `tcp_listen()`."""
        interface = Interface("lo0", {AF_INET: (Binding(LOOPBACK),)})
        received = asyncio.get_running_loop().create_future()

        async def on_connection(reader, writer):
            received.set_result(await reader.read())
            writer.close()

        server = await interface.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            _, writer = await interface.tcp_send(Endpoint(LOOPBACK, port))
            async with wait_closing(writer):
                writer.write(b"hello")
                writer.write_eof()
                assert await asyncio.wait_for(received, timeout=2) == b"hello"

    async def test_listens_on_the_given_port_when_specified(self):
        """An explicit `port` is bound to, rather than choosing one."""
        interface = Interface("lo0", {AF_INET: (Binding(LOOPBACK),)})

        async def on_connection(_, writer):
            writer.close()

        async with wait_closing(await interface.tcp_listen(on_connection)) as probe:
            _, free_port = probe.sockets[0].getsockname()

        server = await interface.tcp_listen(on_connection, port=free_port)
        async with wait_closing(server):
            assert server.sockets[0].getsockname() == (str(LOOPBACK), free_port)


class TestInterfaceUdpSend:
    """`Interface.udp_send()` opens a UDP socket targeting the given
    endpoint."""

    async def test_sends_to_the_remote_endpoint(self):
        """The datagram arrives at the remote endpoint."""
        interface = Interface("lo0", {AF_INET: (Binding(LOOPBACK),)})
        loop = asyncio.get_running_loop()

        listener_transport, listener = await loop.create_datagram_endpoint(SingleDatagramProtocol, local_addr=(str(LOOPBACK), 0))
        with closing(listener_transport):
            _, listener_port = listener_transport.get_extra_info("sockname")
            send_transport, _ = await interface.udp_send(Endpoint(LOOPBACK, listener_port))
            with closing(send_transport):
                send_transport.sendto(b"ping")
                data, _ = await asyncio.wait_for(listener.received, timeout=2)
                assert data == b"ping"


class TestInterfaceUdpListen:
    """`Interface.udp_listen()` listens via one of the interface's own
    bindings, dispatching received datagrams to the given callback."""

    async def test_calls_back_with_the_datagram_and_sender(self):
        """The callback receives the datagram's bytes and the sender's
        endpoint, from a unicast listen (no `group_address`)."""
        interface = Interface("lo0", {AF_INET: (Binding(LOOPBACK),)})
        loop = asyncio.get_running_loop()
        received = loop.create_future()

        async def on_datagram(data, _interface_address, sender, _transport):
            received.set_result((data, sender))

        listen_transport, _ = await interface.udp_listen(on_datagram, port=0)
        with closing(listen_transport):
            _, listen_port = listen_transport.get_extra_info("sockname")

            send_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with closing(send_transport):
                _, sender_port = send_transport.get_extra_info("sockname")
                send_transport.sendto(b"ping", (str(LOOPBACK), listen_port))
                data, sender = await asyncio.wait_for(received, timeout=2)
                assert data == b"ping"
                assert sender == Endpoint(LOOPBACK, sender_port)

    async def test_a_group_address_listens_on_the_group_rather_than_a_bindings_own_address(self):
        """With a `group_address`, the socket binds to the group address
        and port, not one of the interface's own bindings."""
        interface = Interface("lo0", {AF_INET: (Binding(LOOPBACK),)})
        group = IPv4Address("239.255.255.250")

        async def on_datagram(_data, _interface_address, _sender, _transport):
            pass

        transport, _ = await interface.udp_listen(on_datagram, port=1900, group_address=group)
        with closing(transport):
            assert transport.get_extra_info("sockname") == (str(group), 1900)


class TestInterfaceUdpBroadcast:
    """`Interface.udp_broadcast()` picks the binding with the longest
    netmask prefix (the most specific one) to broadcast from."""

    async def test_picks_the_binding_with_the_longest_prefix(self):
        """Given bindings with different prefix lengths, the most
        specific one (highest `prefixlen`) is used."""
        broad = Binding(LOOPBACK, netmask=IPv4Network("127.0.0.0/8"), broadcast=None)
        specific = Binding(LOOPBACK, netmask=IPv4Network("127.0.0.1/32"), broadcast=LOOPBACK)
        interface = Interface("lo0", {AF_INET: (broad, specific)})

        loop = asyncio.get_running_loop()

        # `specific` is the only one of the two that's broadcasting, so
        # if it's chosen, the group address itself becomes reachable.
        listener_transport, listener = await loop.create_datagram_endpoint(SingleDatagramProtocol, local_addr=(str(LOOPBACK), 0))
        with closing(listener_transport):
            _, listener_port = listener_transport.get_extra_info("sockname")
            transport, _ = await interface.udp_broadcast(LOOPBACK, port=listener_port)
            with closing(transport):
                transport.sendto(b"ping")
                data, _ = await asyncio.wait_for(listener.received, timeout=2)
                assert data == b"ping"

    async def test_a_binding_with_no_netmask_sorts_before_none_of_them(self):
        """A binding with no `netmask` at all is treated as the least
        specific (`prefixlen` 0), not preferred over any real prefix."""
        no_netmask = Binding(LOOPBACK, netmask=None, broadcast=None)
        specific = Binding(LOOPBACK, netmask=IPv4Network("127.0.0.1/32"), broadcast=LOOPBACK)
        interface = Interface("lo0", {AF_INET: (no_netmask, specific)})

        loop = asyncio.get_running_loop()

        listener_transport, listener = await loop.create_datagram_endpoint(SingleDatagramProtocol, local_addr=(str(LOOPBACK), 0))
        with closing(listener_transport):
            _, listener_port = listener_transport.get_extra_info("sockname")
            transport, _ = await interface.udp_broadcast(LOOPBACK, port=listener_port)
            with closing(transport):
                transport.sendto(b"ping")
                data, _ = await asyncio.wait_for(listener.received, timeout=2)
                assert data == b"ping"


class TestInterfaceFromNetifaces:
    """Building an `Interface` from `netifaces`, for each requested
    address family - checked against the real loopback interface, rather
    than faked `netifaces` data."""

    def test_matches_the_real_addresses_netifaces_reports_for_loopback(self):
        """The addresses built for the real loopback interface match
        what `netifaces` itself reports for it."""
        loopback_name = next(name for name in netifaces.interfaces() if name.startswith("lo"))
        real_addresses = {IPv4Address(entry["addr"]) for entry in netifaces.ifaddresses(loopback_name)[AF_INET]}

        interface = Interface.from_netifaces(loopback_name, (AF_INET,))

        assert interface.name == loopback_name
        assert set(interface.addresses()) == real_addresses
