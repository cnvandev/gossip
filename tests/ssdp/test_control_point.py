import asyncio
import uuid
from ipaddress import IPv4Address
from uuid import UUID

import pytest
from netifaces import AF_INET

from gossip.http.message import HTTPRequest
from gossip.internet.product import ProductStack
from gossip.internet.uri import URI
from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface
from gossip.network.radio import Radio
from gossip.network.replier import Replier
from gossip.ssdp.client import SSDPClient
from gossip.ssdp.control_point import SSDPControlPoint
from gossip.ssdp.headers import CPFN, CPUUID, TCP_PORT
from gossip.ssdp.uri import SSDP_HOST, SSDP_PORT, SSDPTarget

from ..support.http import echo_request
from ..support.network import real_interface_address

LOOPBACK = IPv4Address("127.0.0.1")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), SSDP_HOST.port)


class TestSSDPControlPointInit:
    """Building an `SSDPControlPoint` - wraps the `SSDPClient` used to
    search, and the `Replier` that listens for `NOTIFY`s on the SSDP
    multicast address."""

    def test_stores_the_given_friendly_name(self):
        """`friendly_name` is stored as-is."""
        assert SSDPControlPoint("my-cp").friendly_name == "my-cp"

    def test_defaults_device_uuid_from_the_machines_own_node(self):
        """Omitting `device_uuid` builds one from the real
        `uuid.getnode()` id, not a fixed or random one."""
        control_point = SSDPControlPoint("my-cp")
        assert control_point.uuid == UUID(int=uuid.getnode())

    def test_stores_a_given_device_uuid(self):
        """A given `device_uuid` is stored as-is."""
        given = UUID(int=1)
        control_point = SSDPControlPoint("my-cp", device_uuid=given)
        assert control_point.uuid is given

    def test_devices_starts_empty(self):
        """`devices` starts out empty, before any `NOTIFY` is seen."""
        assert SSDPControlPoint("my-cp").devices == {}

    def test_client_is_built_with_the_given_radio_and_agent(self):
        """`client` is an `SSDPClient` using the same `radio`/`agent`
        given to the control point."""
        radio = Radio.loopback()
        agent = ProductStack.gossip()
        control_point = SSDPControlPoint("my-cp", radio=radio, agent=agent)
        assert isinstance(control_point.client, SSDPClient)
        assert control_point.client.prompter.radio is radio
        assert control_point.client.agent is agent

    def test_replier_listens_on_the_ssdp_multicast_address_with_the_given_radio(self):
        """`replier` listens for `NOTIFY`s on `SSDP_HOST`, using the same
        `radio` given to the control point."""
        radio = Radio.loopback()
        control_point = SSDPControlPoint("my-cp", radio=radio)
        assert SSDP_HOST in control_point.replier.udp
        assert control_point.replier.radio is radio


class TestSSDPControlPointContextManager:
    """`SSDPControlPoint` as an async context manager just starts/stops
    its own `replier`."""

    async def test_aenter_starts_the_replier_and_returns_the_control_point(self):
        """Entering starts `replier` listening and returns the control
        point itself."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        control_point = SSDPControlPoint("my-cp", radio=radio)

        async with control_point as entered:
            assert entered is control_point
            assert len(control_point.replier.udp_transports) == 1

    async def test_aexit_stops_the_replier(self):
        """Exiting closes every transport `replier` opened."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        control_point = SSDPControlPoint("my-cp", radio=radio)

        async with control_point:
            transport = control_point.replier.udp_transports[0]
        assert transport.is_closing()


class TestSSDPControlPointRespond:
    """`SSDPControlPoint.respond()` feeds `self.devices` from `NOTIFY`
    requests, and never sends a reply - control points don't respond to
    multicast traffic, `SEARCH` included."""

    async def test_a_notify_records_the_device_and_returns_no_response(self):
        """A `NOTIFY` is passed to `notify()` and produces no reply."""
        control_point = SSDPControlPoint("my-cp")
        usn = "uuid:11111111-1111-1111-1111-111111111111::upnp:rootdevice"
        request = HTTPRequest("NOTIFY", URI.parse("*"), {"USN": usn, "NTS": "ssdp:alive"})

        responses = await control_point.respond(request, REMOTE, LOCAL)

        assert tuple(responses) == ()
        assert control_point.devices[URI.parse(usn)]["NTS"] == "ssdp:alive"

    async def test_a_non_notify_request_is_ignored(self):
        """A `SEARCH` (or any other non-`NOTIFY`) request is dropped -
        it's neither responded to nor recorded."""
        control_point = SSDPControlPoint("my-cp")
        request = HTTPRequest("SEARCH", URI.parse("*"), {"ST": "ssdp:all"})

        responses = await control_point.respond(request, REMOTE, LOCAL)

        assert tuple(responses) == ()
        assert control_point.devices == {}


class TestSSDPControlPointNotify:
    """`SSDPControlPoint.notify()` records the sender's metadata under
    its own `USN`, keyed as a `URI`."""

    async def test_records_metadata_keyed_by_the_parsed_usn(self):
        """The request's full header set is stored, keyed by its parsed
        `USN`."""
        control_point = SSDPControlPoint("my-cp")
        usn = "uuid:11111111-1111-1111-1111-111111111111::upnp:rootdevice"
        request = HTTPRequest("NOTIFY", URI.parse("*"), {"USN": usn, "NTS": "ssdp:alive", "Location": "http://10.0.0.5/device.xml"})

        await control_point.notify(request, REMOTE)

        assert control_point.devices[URI.parse(usn)]["Location"] == "http://10.0.0.5/device.xml"

    async def test_a_missing_usn_is_keyed_by_an_empty_uri(self):
        """No `USN` header at all still records under `URI.parse("")`,
        rather than raising or skipping the update."""
        control_point = SSDPControlPoint("my-cp")
        request = HTTPRequest("NOTIFY", URI.parse("*"), {"NTS": "ssdp:alive"})

        await control_point.notify(request, REMOTE)

        assert URI.parse("") in control_point.devices


class TestSSDPControlPointBroadcastSearch:
    """`SSDPControlPoint.broadcast_search()` builds the control point's
    own headers (control-point UUID/friendly name, `ST`, `MX`) on top of
    what `SSDPClient.broadcast_search()` sends, over the real network."""

    async def test_sends_expected_headers(self):
        """`Host`/`CPUUID`/`CPFN`/`ST`/`MX` all land on the sent request."""
        radio = Radio.loopback()
        device_uuid = UUID(int=42)
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            control_point = SSDPControlPoint("my-cp", device_uuid=device_uuid, radio=radio)
            target = SSDPTarget.all()
            replies = await control_point.broadcast_search(target, max_wait=1)

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.headers["Test-Request-Host"] == str(SSDP_HOST)
                assert reply.headers[f"Test-Request-{CPUUID}"] == str(device_uuid)
                assert reply.headers[f"Test-Request-{CPFN}"] == "my-cp"
                assert reply.headers["Test-Request-ST"] == str(target)
                assert reply.headers["Test-Request-MX"] == "1"


class TestSSDPControlPointUnicastSearch:
    """`SSDPControlPoint.unicast_search()` builds the same control-point
    headers as `broadcast_search()`, sent to one address directly."""

    async def test_sends_expected_headers(self):
        """`Host`/`CPUUID`/`CPFN`/`ST` all land on the sent request."""
        radio = Radio.loopback()
        device_uuid = UUID(int=7)
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            control_point = SSDPControlPoint("my-cp", device_uuid=device_uuid, radio=radio)
            target = SSDPTarget.all()
            remote = Endpoint(LOOPBACK, SSDP_PORT)
            response = await control_point.unicast_search(remote, target)

            assert response is not None
            assert response.headers["Test-Request-Host"] == str(remote)
            assert response.headers[f"Test-Request-{CPUUID}"] == str(device_uuid)
            assert response.headers[f"Test-Request-{CPFN}"] == "my-cp"
            assert response.headers["Test-Request-ST"] == str(target)

    async def test_a_given_tcp_port_adds_the_header_naming_it(self):
        """A given `tcp_port` is added as the `TCPPORT.UPNP.ORG` header -
        telling the target where to send an out-of-band reply."""
        radio = Radio.loopback()
        async with Replier(callback=echo_request, udp={SSDP_PORT: HTTPRequest.read_from}, radio=radio):
            control_point = SSDPControlPoint("my-cp", radio=radio)
            target = SSDPTarget.all()
            remote = Endpoint(LOOPBACK, SSDP_PORT)
            response = await control_point.unicast_search(remote, target, tcp_port=54321)

            assert response is not None
            assert response.headers[f"Test-Request-{TCP_PORT}"] == "54321"
