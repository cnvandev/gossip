import asyncio
from contextlib import closing
from ipaddress import IPv4Address

import netifaces
from netifaces import AF_INET

from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface
from gossip.network.radio import Radio

from ..support.asyncio import wait_closing
from ..support.network import SingleDatagramProtocol

LOOPBACK = IPv4Address("127.0.0.1")


class TestRadioAddresses:
    """`Radio.addresses()` - every address bound to any of its
    interfaces."""

    def test_returns_every_interfaces_addresses(self):
        """Every interface's addresses are included."""
        radio = Radio((Interface("eth0", {AF_INET: (Binding(LOOPBACK),)}), Interface("wlan0", {AF_INET: (Binding(IPv4Address("10.0.0.1")),)})))
        assert set(radio.addresses()) == {LOOPBACK, IPv4Address("10.0.0.1")}


class TestRadioTcp:
    """`Radio.tcp_listen()`/`Radio.tcp_send()` round-trip real bytes over
    loopback."""

    async def test_round_trips_bytes(self):
        """A client connected via `tcp_send()` delivers its bytes to
        whatever's listening via `tcp_listen()`."""
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))
        received = asyncio.get_running_loop().create_future()

        async def on_connection(reader, writer):
            received.set_result(await reader.read())
            writer.close()

        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            _, writer = await radio.tcp_send(Endpoint(LOOPBACK, port))
            async with wait_closing(writer):
                writer.write(b"hello")
                writer.write_eof()
                assert await asyncio.wait_for(received, timeout=2) == b"hello"

    async def test_listens_on_the_given_port_when_specified(self):
        """An explicit `port` is bound to, rather than choosing one."""
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))

        async def on_connection(_, writer):
            writer.close()

        async with wait_closing(await radio.tcp_listen(on_connection)) as probe:
            _, free_port = probe.sockets[0].getsockname()

        server = await radio.tcp_listen(on_connection, port=free_port)
        async with wait_closing(server):
            assert server.sockets[0].getsockname() == (str(LOOPBACK), free_port)


class TestRadioUdpSend:
    """`Radio.udp_send()` opens a UDP socket targeting the given
    endpoint."""

    async def test_sends_to_the_remote_endpoint(self):
        """The datagram arrives at the remote endpoint."""
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))
        loop = asyncio.get_running_loop()

        listener_transport, listener = await loop.create_datagram_endpoint(SingleDatagramProtocol, local_addr=(str(LOOPBACK), 0))
        with closing(listener_transport):
            _, listener_port = listener_transport.get_extra_info("sockname")
            send_transport, _ = await radio.udp_send(Endpoint(LOOPBACK, listener_port))
            with closing(send_transport):
                send_transport.sendto(b"ping")
                data, _ = await asyncio.wait_for(listener.received, timeout=2)
                assert data == b"ping"


class TestRadioUdpListen:
    """`Radio.udp_listen()` listens across every interface at once."""

    async def test_listens_on_every_interface(self):
        """Each interface gets its own listening transport."""
        radio = Radio((Interface("eth0", {AF_INET: (Binding(LOOPBACK),)}), Interface("wlan0", {AF_INET: (Binding(LOOPBACK),)})))

        async def on_datagram(_data, _interface_address, _sender, _transport):
            pass

        listeners = await radio.udp_listen(on_datagram, port=0)
        try:
            assert len(listeners) == 2
        finally:
            for transport, _ in listeners:
                transport.close()

    async def test_calls_back_with_the_datagram_and_sender(self):
        """The callback receives the datagram's bytes and the sender's
        endpoint."""
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))
        loop = asyncio.get_running_loop()
        received = loop.create_future()

        async def on_datagram(data, _interface_address, sender, _transport):
            received.set_result((data, sender))

        (listen_transport, _), = await radio.udp_listen(on_datagram, port=0)
        with closing(listen_transport):
            _, listen_port = listen_transport.get_extra_info("sockname")

            send_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with closing(send_transport):
                _, sender_port = send_transport.get_extra_info("sockname")
                send_transport.sendto(b"ping", (str(LOOPBACK), listen_port))
                data, sender = await asyncio.wait_for(received, timeout=2)
                assert data == b"ping"
                assert sender == Endpoint(LOOPBACK, sender_port)


class TestRadioUdpBroadcast:
    """`Radio.udp_broadcast()` broadcasts across every interface at
    once."""

    async def test_broadcasts_on_every_interface(self):
        """Each interface gets its own broadcast transport."""
        radio = Radio((Interface("eth0", {AF_INET: (Binding(LOOPBACK),)}), Interface("wlan0", {AF_INET: (Binding(LOOPBACK),)})))

        broadcasts = await radio.udp_broadcast(LOOPBACK, port=0)
        try:
            assert len(broadcasts) == 2
        finally:
            for transport, _ in broadcasts:
                transport.close()


class TestRadioFromNetifaces:
    """Building a `Radio` from `netifaces`, restricted to a set of
    interface name prefixes and address families - checked against the
    real machine's own interfaces, rather than faked `netifaces` data."""

    def test_includes_every_real_interface_matching_the_requested_prefixes_and_families(self):
        """Every real interface whose name matches a requested prefix,
        and that has an address in a requested family, is included -
        and nothing else is."""
        expected = {name for name in netifaces.interfaces() if name.rstrip("0123456789") in {"en", "lo"} and AF_INET in netifaces.ifaddresses(name)}

        radio = Radio.from_netifaces(interfaces=("en", "lo"), address_families=(AF_INET,))

        assert set(radio.interfaces.keys()) == expected
