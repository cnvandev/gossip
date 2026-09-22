import asyncio
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
from gossip.ssdp.device import SSDPDevice
from gossip.ssdp.uri import SSDP_HOST
from gossip.upnp.resource import UPnPDevice

from ..support.network import NotifyRecorder, collect_notifications, real_interface_address
from ..upnp.descriptor import DummyDevice

LOOPBACK = IPv4Address("127.0.0.1")


class TestSSDPDeviceInit:
    """Building an `SSDPDevice` - wraps a `UPnPDevice` with the `SSDPServer`
    that serves it and the `Prompter` used to announce it."""

    def test_stores_the_upnp_device(self):
        """`upnp_device` is the same object passed in."""
        upnp_device = UPnPDevice(DummyDevice())
        assert SSDPDevice(upnp_device).upnp_device is upnp_device

    def test_defaults_the_path_to_device_xml(self):
        """Omitting `path` defaults it to `/device.xml`."""
        device = SSDPDevice(UPnPDevice(DummyDevice()))
        assert device.path == "/device.xml"

    def test_stores_a_given_path(self):
        """A given `path` is stored as-is."""
        device = SSDPDevice(UPnPDevice(DummyDevice()), path="/custom.xml")
        assert device.path == "/custom.xml"

    def test_server_serves_the_upnp_device_at_the_given_path(self):
        """`server` serves `upnp_device` at exactly `path`."""
        upnp_device = UPnPDevice(DummyDevice())
        device = SSDPDevice(upnp_device, path="/custom.xml")
        assert device.server.resources == {URI.parse("/custom.xml"): upnp_device}

    def test_prompter_deserializes_http_responses(self):
        """`prompter` is built to deserialize `HTTPResponse`s."""
        device = SSDPDevice(UPnPDevice(DummyDevice()))
        assert device.prompter.deserializer == HTTPResponse.read_from

    def test_a_given_radio_is_used_by_both_the_prompter_and_the_server(self):
        """A given `radio` is used by both `prompter` and `server`'s own
        replier - they announce on the same interfaces."""
        radio = Radio.loopback()
        device = SSDPDevice(UPnPDevice(DummyDevice()), radio=radio)
        assert device.prompter.radio is radio
        assert device.server.replier.radio is radio

    def test_prompter_defaults_to_a_real_netifaces_radio(self):
        """Omitting `radio` builds a real one from the machine's own
        interfaces, rather than leaving it unset."""
        device = SSDPDevice(UPnPDevice(DummyDevice()))
        assert isinstance(device.prompter.radio, Radio)


class TestSSDPDeviceNotificationRequest:
    """`SSDPDevice.notification_request()` builds the `NOTIFY` request sent
    out on one interface - a pure function of the given headers and that
    interface's own outgoing address, with no networking of its own."""

    def test_method_is_notify_and_target_is_the_wildcard(self):
        """The request method is always `NOTIFY`, and its target is `*`
        per the SSDP `NOTIFY` spec, not the device's own served path."""
        device = SSDPDevice(UPnPDevice(DummyDevice()))
        request = device.notification_request({}, Endpoint(LOOPBACK, 1900))
        assert request.method == "NOTIFY"
        assert str(request.target) == "*"

    def test_keeps_the_given_headers(self):
        """Every given header is kept on the built request."""
        device = SSDPDevice(UPnPDevice(DummyDevice()))
        request = device.notification_request({"NT": "upnp:rootdevice", "NTS": "ssdp:alive"}, Endpoint(LOOPBACK, 1900))
        assert request.headers["NT"] == "upnp:rootdevice"
        assert request.headers["NTS"] == "ssdp:alive"

    def test_location_is_an_http_url_to_the_devices_path_via_the_local_address(self):
        """`Location` is an absolute `http://` URL combining `local` with
        the device's own served `path` - not `local` alone, and not
        `path` alone."""
        device = SSDPDevice(UPnPDevice(DummyDevice()), path="/custom.xml")
        request = device.notification_request({}, Endpoint(IPv4Address("10.0.0.5"), 1900))
        assert request.headers["Location"] == "http://10.0.0.5:1900/custom.xml"

    def test_location_overrides_any_location_already_in_headers(self):
        """A `Location` already present in the given headers is replaced,
        not kept - it's the built one that's actually reachable."""
        device = SSDPDevice(UPnPDevice(DummyDevice()))
        request = device.notification_request({"Location": "urn:not-a-url"}, Endpoint(IPv4Address("10.0.0.5"), 1900))
        assert request.headers["Location"] == "http://10.0.0.5:1900/device.xml"


class TestSSDPDeviceNotify:
    """`SSDPDevice.notify()` broadcasts one `NOTIFY` per target the device
    matches, on every interface, waiting for them to actually be sent."""

    async def test_sends_one_notification_per_target(self):
        """A device with no embedded services/devices matches 3 targets
        (its root device, its UDN alone, and its own device type) - one
        `NOTIFY` goes out for each."""
        device = SSDPDevice(UPnPDevice(DummyDevice()), radio=Radio.loopback())

        requests = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            device.notify(URI.ssdp("alive")),
        )
        assert len(requests[0]) == 3
        assert all(request.method == "NOTIFY" for request in requests[0])

    async def test_notification_headers_match_the_subtype_and_target(self):
        """Each `NOTIFY`'s `NTS` is the given subtype, `NT` is its own
        target, and `USN`/config headers come from the device's own
        per-target data."""
        upnp_device = UPnPDevice(DummyDevice())
        device = SSDPDevice(upnp_device, radio=Radio.loopback())

        requests, _ = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            device.notify(URI.ssdp("alive")),
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
        device = SSDPDevice(UPnPDevice(DummyDevice()), radio=Radio.loopback())

        requests, _ = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            device.notify(URI.ssdp("byebye")),
        )
        assert all(request.headers["NTS"] == "ssdp:byebye" for request in requests)

    async def test_location_reflects_the_actual_sending_interfaces_address(self):
        """`Location` on each sent request is built from the real address
        it was actually sent from, not a fixed or guessed one."""
        device = SSDPDevice(UPnPDevice(DummyDevice()), path="/device.xml", radio=Radio.loopback())

        requests, _ = await asyncio.gather(
            collect_notifications(3, SSDP_HOST.port),
            device.notify(URI.ssdp("alive")),
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
        device = SSDPDevice(UPnPDevice(DummyDevice()), radio=radio)

        requests, _ = await asyncio.gather(
            collect_notifications(6, SSDP_HOST.port),
            device.notify(URI.ssdp("alive")),
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
        device = SSDPDevice(UPnPDevice(DummyDevice()), radio=Radio.loopback())
        await asyncio.wait_for(device.notify(URI.ssdp("alive")), timeout=2)


class TestSSDPDeviceContextManager:
    """`SSDPDevice` as an async context manager - starts its `server` and
    announces itself as `ssdp:alive` on entry, and as `ssdp:byebye` on
    exit."""

    async def test_aenter_returns_the_started_server(self):
        """Entering returns the started `server`."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        device = SSDPDevice(UPnPDevice(DummyDevice()), radio=radio)

        async with device as server:
            assert server is device.server

    async def test_aenter_sends_an_alive_notification_on_every_interface(self):
        """Entering broadcasts `ssdp:alive` notifications before returning."""
        address = real_interface_address()
        if address is None:
            pytest.skip("no real (non-loopback) network interface available")
        radio = Radio((Interface("real", {AF_INET: (Binding(address, broadcast=address),)}),))
        recorder = NotifyRecorder()

        async with (
            Replier(callback=recorder, udp={SSDP_HOST: HTTPRequest.read_from}, radio=radio),
            SSDPDevice(UPnPDevice(DummyDevice()), radio=radio),
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
            async with SSDPDevice(UPnPDevice(DummyDevice()), radio=radio):
                await wait_until(lambda: len(recorder.received) >= 3)
            await asyncio.wait_for(wait_until(lambda: len(recorder.received) >= 6), timeout=2)

        byebyes = [request for request in recorder.received if request.headers["NTS"] == "ssdp:byebye"]
        assert len(byebyes) == 3

    async def test_aexit_logs_rather_than_raises_when_notify_fails(self):
        """A failure sending the `byebye` notification is logged, not
        raised - a flaky interface on the way out shouldn't crash the
        caller."""
        broken_radio = Radio((Interface("broken", {}),))
        device = SSDPDevice(UPnPDevice(DummyDevice()), radio=broken_radio)

        with pytest.raises(IndexError):
            await device.notify(URI.ssdp("byebye"))

        # `__aexit__()` hits the exact same failure, but swallows it.
        await device.__aexit__(None, None, None)


async def wait_until(condition, interval: float = 0.01) -> None:
    """Polls `condition` until it's true."""
    while not condition():
        await asyncio.sleep(interval)
