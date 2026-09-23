import asyncio
from http import HTTPStatus
from ipaddress import IPv4Address

from gossip.http.message import HTTPRequest
from gossip.network.radio import Radio
from gossip.network.replier import Replier
from gossip.ssdp.client import SSDPClient
from gossip.ssdp.headers import TCP_PORT
from gossip.ssdp.uri import SSDP_PORT

from ..support.http import echo_request

LOOPBACK = IPv4Address("127.0.0.1")


class TestSSDPClientBroadcastSearch:
    """`SSDPClient.broadcast_search()` broadcasts a mandatory
    `ssdp:discover` `M-SEARCH` on the SSDP multicast address/port, and
    streams back deserialized replies."""

    async def test_sends_an_m_search_declaring_discover_with_no_tcp_port_header(self):
        """The request method is `M-SEARCH`, with `ssdp:discover`
        declared mandatory via a quoted `Man` header - and, with no
        `tcp_port` given, no `TCPPORT.UPNP.ORG` header at all."""
        radio = Radio.loopback()
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            client = SSDPClient(radio=radio)
            replies = await client.broadcast_search()

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.status == HTTPStatus.OK
                assert reply.headers["Test-Request-Method"] == "M-SEARCH"
                assert reply.headers["Test-Request-Man"] == '"ssdp:discover"'
                assert f"Test-Request-{TCP_PORT}" not in reply.headers

    async def test_keeps_given_headers(self):
        """Given headers are kept on the sent request."""
        radio = Radio.loopback()
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            client = SSDPClient(radio=radio)
            replies = await client.broadcast_search({"ST": "ssdp:all"})

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.headers["Test-Request-ST"] == "ssdp:all"

    async def test_a_given_tcp_port_is_sent_as_a_header(self):
        """A given `tcp_port` is added as the `TCPPORT.UPNP.ORG` header,
        telling responders where to send an out-of-band reply."""
        radio = Radio.loopback()
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            client = SSDPClient(radio=radio)
            replies = await client.broadcast_search(tcp_port=12345)

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.headers[f"Test-Request-{TCP_PORT}"] == "12345"


class TestSSDPClientUnicastSearch:
    """`SSDPClient.unicast_search()` sends a mandatory `ssdp:discover`
    `M-SEARCH` directly to one address on the SSDP port, and returns its
    one reply."""

    async def test_sends_to_the_given_address_declaring_discover(self):
        """The request declares the discover extension the same way
        `broadcast_search()` does, and returns the real reply."""
        radio = Radio.loopback()
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            client = SSDPClient(radio=radio)
            response = await client.unicast_search(LOOPBACK)

            assert response is not None
            assert response.headers["Test-Request-Method"] == "M-SEARCH"
            assert response.headers["Test-Request-Man"] == '"ssdp:discover"'

    async def test_accepts_a_hostname_string_address(self):
        """A plain string address is parsed to an IP before sending,
        rather than requiring a caller to build one themselves."""
        radio = Radio.loopback()
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            client = SSDPClient(radio=radio)
            response = await client.unicast_search("127.0.0.1")

            assert response is not None
            assert response.headers["Test-Request-Method"] == "M-SEARCH"

    async def test_keeps_given_headers(self):
        """Given headers are kept on the sent request."""
        radio = Radio.loopback()
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            client = SSDPClient(radio=radio)
            response = await client.unicast_search(LOOPBACK, {"ST": "ssdp:all"})

            assert response is not None
            assert response.headers["Test-Request-ST"] == "ssdp:all"
