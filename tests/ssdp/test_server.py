import asyncio
from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

import pytest
from netifaces import AF_INET

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.uri import URI
from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface
from gossip.network.radio import Radio
from gossip.network.replier import Replier
from gossip.ssdp.headers import SEARCH_PORT, TCP_PORT
from gossip.ssdp.responder import SSDPResponder
from gossip.ssdp.server import SSDPServer
from gossip.ssdp.uri import SSDP_HOST
from gossip.upnp.resource import UPnPDevice

from ..support.http import echo_request
from ..support.network import NotifyRecorder, collect_notifications, free_tcp_port, real_interface_address
from ..support.resources import InMemoryResource
from ..upnp.descriptor import DummyDevice

LOOPBACK = IPv4Address("127.0.0.1")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), SSDP_HOST.port)


class TestSSDPServerInit:
    """Building an `SSDPServer` - serves its given resources over HTTP/SSDP,
    and builds the `Prompter` used to announce them."""

    def test_serves_the_given_resources(self):
        """`resources` is served exactly as given."""
        upnp_device = UPnPDevice(DummyDevice())
        resources = {URI.parse("/custom.xml"): upnp_device}
        assert SSDPServer(resources).resources == resources

    def test_prompter_deserializes_http_responses(self):
        """`prompter` is built to deserialize `HTTPResponse`s."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()))
        assert server.prompter.deserializer == HTTPResponse.read_from

    def test_a_given_radio_is_used_by_both_the_prompter_and_the_replier(self):
        """A given `radio` is used by both `prompter` and `replier` -
        announcements and requests go out on the same interfaces."""
        radio = Radio.loopback()
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=radio)
        assert server.prompter.radio is radio
        assert server.replier.radio is radio

    def test_prompter_defaults_to_a_real_netifaces_radio(self):
        """Omitting `radio` builds a real one from the machine's own
        interfaces, rather than leaving it unset."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()))
        assert isinstance(server.prompter.radio, Radio)


class TestSSDPServerInitDefaults:
    """Building an `SSDPServer` without an explicit `replier`/`responder`
    wires up the multicast + unicast SSDP listeners and an
    `SSDPResponder` for `resources`."""

    def test_replier_listens_for_multicast_and_unicast_udp_on_the_ssdp_port_by_default(self):
        """With no `udp_port` given, both the multicast group and a plain
        unicast UDP/TCP listen use the default SSDP port."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=Radio.loopback())
        assert SSDP_HOST in server.replier.udp
        assert SSDP_HOST.port in server.replier.udp
        assert SSDP_HOST.port in server.replier.tcp

    def test_replier_also_listens_on_a_given_udp_port(self):
        """A custom `udp_port` is used for the unicast UDP/TCP listeners,
        alongside the (fixed) multicast group listen."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), udp_port=12345, radio=Radio.loopback())
        assert SSDP_HOST in server.replier.udp
        assert 12345 in server.replier.udp
        assert 12345 in server.replier.tcp

    def test_stores_a_given_replier_instead_of_building_one(self):
        """A given `replier` is used as-is, not rebuilt."""
        radio = Radio.loopback()
        replier = Replier(callback=echo_request, udp={0: HTTPRequest.read_from}, radio=radio)
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), replier=replier, radio=radio)
        assert server.replier is replier

    def test_defaults_to_an_ssdp_responder_with_no_search_port_header_on_the_default_port(self):
        """Using the default SSDP port adds no `SEARCHPORT.UPNP.ORG`
        static header - there's nothing non-standard to advertise."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=Radio.loopback())
        assert isinstance(server.responder, SSDPResponder)
        assert str(SEARCH_PORT) not in server.responder.static_headers

    def test_a_custom_udp_port_is_advertised_via_the_search_port_header(self):
        """A non-default `udp_port` is advertised via the
        `SEARCHPORT.UPNP.ORG` static header, so unicast searchers know
        where else to reach it."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), udp_port=12345, radio=Radio.loopback())
        assert server.responder.static_headers[str(SEARCH_PORT)] == "12345"

    def test_stores_a_given_responder_instead_of_building_one(self):
        """A given `responder` is used as-is, not rebuilt."""
        responder = SSDPResponder({URI.parse("/thing"): InMemoryResource()})
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), responder=responder, radio=Radio.loopback())
        assert server.responder is responder


class TestSSDPServerNotificationRequest:
    """`SSDPServer.notification_request()` builds the `NOTIFY` request sent
    out on one interface - a pure function of the given headers and that
    interface's own outgoing address, with no networking of its own.

    `headers["Location"]` is expected to already be the (path-only) `URI`
    of the resource being announced - it's resolved into an absolute URL
    via `local`, not set from scratch.
    """

    def test_method_is_notify_and_target_is_the_wildcard(self):
        """The request method is always `NOTIFY`, and its target is `*`
        per the SSDP `NOTIFY` spec, not the device's own served path."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()))
        request = server.notification_request({"Location": "/device.xml"}, Endpoint(LOOPBACK, 1900))
        assert request.method == "NOTIFY"
        assert str(request.target) == "*"

    def test_keeps_the_given_headers(self):
        """Every given header is kept on the built request."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()))
        request = server.notification_request(
            {"NT": "upnp:rootdevice", "NTS": "ssdp:alive", "Location": "/device.xml"},
            Endpoint(LOOPBACK, 1900),
        )
        assert request.headers["NT"] == "upnp:rootdevice"
        assert request.headers["NTS"] == "ssdp:alive"

    def test_location_is_resolved_to_an_absolute_url_via_the_local_address(self):
        """`Location` becomes an absolute `http://` URL combining `local`
        with the given `Location` path - not `local` alone, and not the
        path alone."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()))
        request = server.notification_request({"Location": "/custom.xml"}, Endpoint(IPv4Address("10.0.0.5"), 1900))
        assert request.headers["Location"] == "http://10.0.0.5:1900/custom.xml"


class TestSSDPServerNotify:
    """`SSDPServer.notify()` broadcasts one `NOTIFY` per target the device
    matches, on every interface, waiting for them to actually be sent."""

    async def test_sends_one_notification_per_target(self):
        """A device with no embedded services/devices matches 3 targets
        (its root device, its UDN alone, and its own device type) - one
        `NOTIFY` goes out for each."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=Radio.loopback())

        requests = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            server.notify(URI.ssdp("alive")),
        )
        assert len(requests[0]) == 3
        assert all(request.method == "NOTIFY" for request in requests[0])

    async def test_notification_headers_match_the_subtype_and_target(self):
        """Each `NOTIFY`'s `NTS` is the given subtype, `NT` is its own
        target, and `USN`/config headers come from the device's own
        per-target data."""
        upnp_device = UPnPDevice(DummyDevice())
        server = SSDPServer.server_for(upnp_device, radio=Radio.loopback())

        requests, _ = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            server.notify(URI.ssdp("alive")),
        )

        by_target = {request.headers["NT"]: request for request in requests}
        assert set(by_target) == set(upnp_device.data)
        for target, subresource_headers in upnp_device.data.items():
            request = by_target[target]
            assert request.headers["NTS"] == "ssdp:alive"
            assert request.headers["Host"] == str(SSDP_HOST)
            assert request.headers["Cache-Control"] == "max-age=1800"
            assert request.headers["USN"] == subresource_headers["USN"]

    async def test_byebye_subtype_is_reflected_in_nts(self):
        """A `byebye` notify sets `NTS` to `ssdp:byebye`, not `ssdp:alive`."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=Radio.loopback())

        requests, _ = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            server.notify(URI.ssdp("byebye")),
        )
        assert all(request.headers["NTS"] == "ssdp:byebye" for request in requests)

    async def test_location_reflects_the_actual_sending_interfaces_address(self):
        """`Location` on each sent request is built from the real address
        it was actually sent from, not a fixed or guessed one."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), path="/device.xml", radio=Radio.loopback())

        requests, _ = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            server.notify(URI.ssdp("alive")),
        )
        for request in requests:
            location = URI.parse(request.headers["Location"])
            assert location.scheme == "http"
            assert location.hostname == str(LOOPBACK)
            assert location.path == "/device.xml"

    async def test_regenerates_the_notification_per_interface(self):
        """With more than one interface, every one of them gets its own
        `NOTIFY` per target, each with its own `Location` - the same
        headers aren't just reused verbatim across interfaces."""
        radio = Radio((
            Interface("eth0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),
            Interface("wlan0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),
        ))
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=radio)

        requests, _ = await asyncio.gather(
            collect_notifications(6, SSDP_HOST.port),
            server.notify(URI.ssdp("alive")),
        )

        locations_by_target: dict[str, set[str]] = {}
        for request in requests:
            locations_by_target.setdefault(request.headers["NT"], set()).add(request.headers["Location"])

        assert len(locations_by_target) == 3
        assert all(len(locations) == 2 for locations in locations_by_target.values())

    async def test_does_not_hang_waiting_for_a_reply(self):
        """`NOTIFY` never gets a reply - awaiting `notify()` completes once
        the sends themselves are done, rather than hanging forever waiting
        for one that will never come."""
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=Radio.loopback())
        await asyncio.wait_for(server.notify(URI.ssdp("alive")), timeout=2)


class TestSSDPServerContextManager:
    """`SSDPServer` as an async context manager - starts listening and
    announces itself as `ssdp:alive` on entry, and as `ssdp:byebye` on
    exit."""

    async def test_aenter_returns_itself(self):
        """Entering returns the `SSDPServer` itself."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=radio)

        async with server as entered:
            assert entered is server

    async def test_aenter_sends_an_alive_notification_on_every_interface(self):
        """Entering broadcasts `ssdp:alive` notifications before returning."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        recorder = NotifyRecorder()

        async with (
            Replier(callback=recorder, udp={SSDP_HOST: HTTPRequest.read_from}, radio=radio),
            SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=radio),
        ):
            await asyncio.wait_for(wait_until(lambda: len(recorder.received) >= 3), timeout=2)
            # Asserted before leaving this block - exiting it sends the
            # `byebye` notifications, which would otherwise race this
            # assertion on the same recorder.
            assert all(request.headers["NTS"] == "ssdp:alive" for request in recorder.received)

    async def test_aexit_sends_a_byebye_notification_on_every_interface(self):
        """Exiting broadcasts `ssdp:byebye` notifications."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        recorder = NotifyRecorder()

        async with Replier(callback=recorder, udp={SSDP_HOST: HTTPRequest.read_from}, radio=radio):
            async with SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=radio):
                await wait_until(lambda: len(recorder.received) >= 3)
            await asyncio.wait_for(wait_until(lambda: len(recorder.received) >= 6), timeout=2)

        byebyes = [request for request in recorder.received if request.headers["NTS"] == "ssdp:byebye"]
        assert len(byebyes) == 3

    async def test_aexit_logs_rather_than_raises_when_notify_fails(self):
        """A failure sending the `byebye` notification is logged, not
        raised - a flaky interface on the way out shouldn't crash the
        caller."""
        broken_radio = Radio((Interface("broken", {}),))
        server = SSDPServer.server_for(UPnPDevice(DummyDevice()), radio=broken_radio)

        with pytest.raises(IndexError):
            await server.notify(URI.ssdp("byebye"))

        # `__aexit__()` hits the exact same failure, but swallows it.
        await server.__aexit__(None, None, None)


class TestSSDPServerRespond:
    """`SSDPServer.respond()` delegates to its own `responder`, and
    redirects the response out-of-band over TCP instead when the request
    carries a `TCPPORT.UPNP.ORG` header."""

    async def test_returns_the_responders_replies_with_no_tcp_port_header(self):
        """No `TCPPORT.UPNP.ORG` header: the responder's own replies are
        returned directly, unchanged."""
        server = SSDPServer.server_for(InMemoryResource(b"hi", {"Content-Type": "text/plain"}), path="/thing", radio=Radio.loopback())
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/thing"))

        (response,) = await server.respond(request, REMOTE, LOCAL)

        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert await response.body.read() == b"hi"

    async def test_a_tcp_port_header_sends_out_of_band_and_returns_nothing(self):
        """A `TCPPORT.UPNP.ORG` header sends the response out-of-band, as
        a real TCP connection to that port, instead of returning it
        directly.

        The callback here never reads the incoming prompt's own body -
        the `Replier`'s dispatch loop doesn't either, it only parses
        headers before calling back - so this doesn't depend on the
        response's body at all, only on our own reply's
        `Connection: close` closing the connection once we're done with
        it.
        """
        radio = Radio.loopback()
        port = await free_tcp_port(radio)
        received: list[HTTPResponse] = []

        async def capture_response(response: HTTPResponse, remote: Endpoint, local: Endpoint) -> tuple[HTTPResponse]:
            received.append(response)
            return (HTTPResponse(HTTPStatus.OK, {"Connection": "close"}),)

        async with Replier(callback=capture_response, tcp={port: HTTPResponse.read_from}, radio=radio):
            server = SSDPServer.server_for(InMemoryResource(b"hi", {"Content-Type": "text/plain"}), path="/thing", radio=radio)
            request = HTTPRequest(HTTPMethod.GET, URI.parse("/thing"), {str(TCP_PORT): str(port)})

            responses = await server.respond(request, Endpoint(LOOPBACK, 0), LOCAL)

            assert tuple(responses) == ()
            assert len(received) == 1
            assert received[0].status == HTTPStatus.OK
            assert received[0].headers["Content-Type"] == "text/plain"


async def wait_until(condition, interval: float = 0.01) -> None:
    """Polls `condition` until it's true."""
    while not condition():
        await asyncio.sleep(interval)
