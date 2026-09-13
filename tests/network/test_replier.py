import asyncio
import contextlib
from http import HTTPStatus
from ipaddress import IPv4Address

import pytest
from netifaces import AF_INET

from gossip.asyncio.protocol.reply import DatagramReplyProtocol
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.uri import URI
from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio
from gossip.network.replier import Replier

from ..support.asyncio import wait_closing
from ..support.http import echo_request
from ..support.network import await_reply, free_tcp_port, free_udp_port, real_interface_address

LOOPBACK = IPv4Address("127.0.0.1")
ROOT = URI.parse("/")


class TestReplierInit:
    """Building a `Replier`."""

    def test_defaults_to_no_tcp_or_udp_listeners(self):
        """Omitting `tcp`/`udp` leaves both empty."""
        replier = Replier(callback=echo_request, radio=Radio.loopback())
        assert replier.tcp == {}
        assert replier.udp == {}

    def test_defaults_to_no_servers_or_transports_before_entering(self):
        """`tcp_servers`/`udp_transports` are empty until entered."""
        replier = Replier(callback=echo_request, radio=Radio.loopback())
        assert replier.tcp_servers == ()
        assert replier.udp_transports == ()

    def test_stores_the_given_radio(self):
        """A given `radio` is stored as-is."""
        radio = Radio.loopback()
        replier = Replier(callback=echo_request, radio=radio)
        assert replier.radio is radio

    def test_defaults_to_a_real_netifaces_radio(self):
        """Omitting `radio` builds a real one from the machine's own
        interfaces, rather than leaving it unset."""
        replier = Replier(callback=echo_request)
        assert isinstance(replier.radio, Radio)


class TestReplierEnter:
    """`Replier.__aenter__()` needs at least one TCP or UDP listener to
    actually start."""

    async def test_raises_without_any_tcp_or_udp_listeners(self):
        """With neither `tcp` nor `udp` given, entering raises."""
        with pytest.raises(ValueError):
            async with Replier(callback=echo_request, radio=Radio.loopback()):
                pass


class TestReplierTcp:
    """`Replier`'s TCP listeners deserialize an incoming request, pass it
    to `callback`, and write back whatever replies it returns."""

    async def test_calls_back_and_replies_to_the_connection(self):
        """The reply written back is exactly what `callback` returned."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))

            assert reply is not None
            assert reply.status == HTTPStatus.OK
            assert reply.headers["Test-Request-Method"] == "GET"

    async def test_each_port_uses_its_own_deserializer(self):
        """Multiple TCP entries each use their own deserializer - not
        whichever one happened to be defined last in `tcp`."""

        async def deserializer_one(reader):
            request = await HTTPRequest.read_from(reader)
            if request is not None:
                request.headers["X-Deserializer"] = "one"
            return request

        async def deserializer_two(reader):
            request = await HTTPRequest.read_from(reader)
            if request is not None:
                request.headers["X-Deserializer"] = "two"
            return request

        radio = Radio.loopback()
        port_one = await free_tcp_port(radio)
        port_two = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port_one: deserializer_one, port_two: deserializer_two}, radio=radio):
            prompter = Prompter(HTTPResponse.read_from, radio=radio)

            reply_one = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port_one))
            reply_two = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port_two))

            assert reply_one is not None
            assert reply_one.headers["Test-Request-X-Deserializer"] == "one"
            assert reply_two is not None
            assert reply_two.headers["Test-Request-X-Deserializer"] == "two"

    async def test_an_unparseable_request_never_reaches_the_callback(self):
        """A request the deserializer can't parse is dropped - the
        connection is simply closed, with no reply and no callback."""
        called = False

        async def respond(request, remote, local):
            nonlocal called
            called = True
            return (HTTPResponse(HTTPStatus.OK),)

        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=respond, tcp={port: HTTPRequest.read_from}, radio=radio):
            reader, writer = await asyncio.open_connection(str(LOOPBACK), port)
            writer.write(b"not a valid HTTP request\r\n\r\n")
            await writer.drain()
            writer.write_eof()
            data = await reader.read()
            writer.close()
            await writer.wait_closed()

        assert data == b""
        assert called is False

    async def test_records_its_own_server_for_closing_later(self):
        """The started `Server` is recorded on `tcp_servers`."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio) as replier:
            assert len(replier.tcp_servers) == 1
            assert replier.tcp_servers[0].is_serving()


class TestReplierUdp:
    """`Replier`'s UDP listeners deserialize an incoming datagram, pass
    it to `callback`, and send back whatever replies it returns - to a
    plain unicast port, or a multicast group address."""

    async def test_a_unicast_port_calls_back_and_replies_to_the_sender(self):
        """A plain unicast port listen calls back with the deserialized
        prompt, and sends the reply straight back to the sender."""
        radio = Radio.loopback()

        async with Replier(callback=echo_request, udp={0: HTTPRequest.read_from}, radio=radio) as replier:
            _, port = replier.udp_transports[0].get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply = await prompter.prompt_udp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))

            assert reply is not None
            assert reply.status == HTTPStatus.OK
            assert reply.headers["Test-Request-Method"] == "GET"

    async def test_an_unparseable_datagram_is_never_passed_to_the_callback(self):
        """A datagram the deserializer can't parse is dropped - no reply
        is ever sent back."""
        radio = Radio.loopback()
        loop = asyncio.get_running_loop()

        async with Replier(callback=echo_request, udp={0: HTTPRequest.read_from}, radio=radio) as replier:
            _, port = replier.udp_transports[0].get_extra_info("sockname")

            sender_transport, listener = await loop.create_datagram_endpoint(DatagramReplyProtocol, local_addr=(str(LOOPBACK), 0))
            with contextlib.closing(sender_transport):
                sender_transport.sendto(b"not a valid HTTP request\r\n\r\n", (str(LOOPBACK), port))
                with pytest.raises(TimeoutError):
                    await await_reply(listener, timeout=0.2)

    async def test_a_group_address_that_cant_be_routed_raises(self):
        """An `Endpoint` key that can't actually be reached (loopback,
        typically - it isn't in the system's multicast routes unless
        one's been added for it) raises, rather than silently binding
        to a group address nothing will ever be delivered to."""
        radio = Radio.loopback()
        group = Endpoint(IPv4Address("239.255.255.250"), 1900)

        with pytest.raises(ValueError):
            async with Replier(callback=echo_request, udp={group: HTTPRequest.read_from}, radio=radio):
                pass

    async def test_a_group_address_calls_back_and_replies_over_a_real_interface(self):
        """Bound to a real (non-loopback) interface, a multicast group
        listen calls back with the deserialized prompt and replies to
        the sender - the same as a unicast listen does."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")

        # `broadcast` has to be set for `Interface.udp_broadcast()` (via
        # `Prompter.broadcast()`) to target `group` at all - otherwise
        # it falls back to looping the datagram back to `address`
        # itself instead of actually sending it to the group.
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        group = Endpoint(IPv4Address("239.255.255.250"), 1900)

        async with Replier(callback=echo_request, udp={group: HTTPRequest.read_from}, radio=radio):
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            future = await prompter.broadcast(HTTPRequest("GET", ROOT), group)
            replies = await asyncio.wait_for(future, timeout=2)

            [result] = replies
            assert result is not None
            reply = await HTTPResponse.read_from(result)
            assert reply is not None
            assert reply.status == HTTPStatus.OK
            assert reply.headers["Test-Request-Method"] == "GET"

    async def test_an_unparseable_group_datagram_is_never_passed_to_the_callback(self):
        """A multicast datagram the deserializer can't parse is dropped -
        no reply is ever sent back."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")

        radio = Radio((Interface("real", {AF_INET: (Binding(address),)}),))
        group = Endpoint(IPv4Address("239.255.255.250"), 1901)
        loop = asyncio.get_running_loop()

        async with Replier(callback=echo_request, udp={group: HTTPRequest.read_from}, radio=radio):
            sender_transport, listener = await loop.create_datagram_endpoint(DatagramReplyProtocol, local_addr=(str(address), 0))
            with contextlib.closing(sender_transport):
                sender_transport.sendto(b"not a valid HTTP request\r\n\r\n", (str(group.address), group.port))
                with pytest.raises(TimeoutError):
                    await await_reply(listener, timeout=0.2)

    async def test_each_port_uses_its_own_deserializer(self):
        """Multiple UDP entries each use their own deserializer - not
        whichever one happened to be defined last in `udp`."""

        async def deserializer_one(pair):
            request = await HTTPRequest.read_from(pair)
            if request is not None:
                request.headers["X-Deserializer"] = "one"
            return request

        async def deserializer_two(pair):
            request = await HTTPRequest.read_from(pair)
            if request is not None:
                request.headers["X-Deserializer"] = "two"
            return request

        radio = Radio.loopback()
        port_one = await free_udp_port(radio)
        port_two = await free_udp_port(radio)

        async with Replier(callback=echo_request, udp={port_one: deserializer_one, port_two: deserializer_two}, radio=radio):
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply_one = await prompter.prompt_udp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port_one))
            reply_two = await prompter.prompt_udp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port_two))

            assert reply_one is not None
            assert reply_one.headers["Test-Request-X-Deserializer"] == "one"
            assert reply_two is not None
            assert reply_two.headers["Test-Request-X-Deserializer"] == "two"

    async def test_records_its_own_transports_for_closing_later(self):
        """Every started UDP transport is recorded on `udp_transports`."""
        radio = Radio.loopback()

        async with Replier(callback=echo_request, udp={0: HTTPRequest.read_from}, radio=radio) as replier:
            assert len(replier.udp_transports) == 1
            assert not replier.udp_transports[0].is_closing()


class TestReplierExit:
    """`Replier.__aexit__()` closes every socket `__aenter__()` opened."""

    async def test_closes_the_tcp_server_freeing_its_port(self):
        """The TCP server is actually closed - its port is immediately
        reusable, not left bound."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio) as replier:
            server = replier.tcp_servers[0]

        assert not server.is_serving()

        async def close_immediately(_, writer):
            writer.close()

        async with wait_closing(await radio.tcp_listen(close_immediately, port=port)):
            pass

    async def test_closes_the_udp_transport(self):
        """The UDP transport is actually closed, not left open."""
        radio = Radio.loopback()

        async with Replier(callback=echo_request, udp={0: HTTPRequest.read_from}, radio=radio) as replier:
            transport = replier.udp_transports[0]

        assert transport.is_closing()
