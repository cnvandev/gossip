from asyncio import run as run_async
from ipaddress import IPv4Address
from uuid import UUID

from gossip.http.message import HTTPRequest
from gossip.http.predicate import StringPredicate
from gossip.http.resource import ResourceCollection
from gossip.http.responder import HTTPResponder
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.ssdp.extension import DISCOVER
from gossip.upnp.resource import UPnPDevice

from ..upnp.descriptor import DummyDevice

STAR_PATH = URI.parse("*")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), 80)
UDN = UUID("11111111-1111-1111-1111-111111111111")


class TestDiscoverExtensionSearch:
    """`DiscoverExtension.search()` responds once per matching target under the
    responder's registered resources, for either an exact `ST` target or the
    `ssdp:all` wildcard."""

    def test_ssdp_all_matches_every_target_on_the_device(self):
        """`ssdp:all` matches every target on the device."""
        device = DummyDevice("mydevice", udn=UDN)
        device_uri = URI.parse("/device.xml")
        resource = HTTPResponder({device_uri: UPnPDevice(device)})

        request = HTTPRequest("SEARCH", STAR_PATH, {"ST": "ssdp:all"})
        responses = run_async(DISCOVER.search(resource, request, {}, {}, REMOTE, LOCAL))

        # A leaf device with no children/services has 3 targets: the
        # root-device target, its bare UDN, and its device type.
        assert len(responses) == 3
        targets = {response.headers["ST"] for response in responses}
        assert targets == {str(device.deviceType), str(device.UDN), "upnp:rootdevice"}

    def test_an_unrelated_target_matches_nothing(self):
        """An `ST` naming an unrelated target matches nothing."""
        device = DummyDevice("mydevice", udn=UDN)
        device_uri = URI.parse("/device.xml")
        resource = HTTPResponder({device_uri: UPnPDevice(device)})

        request = HTTPRequest("SEARCH", STAR_PATH, {"ST": "urn:schemas-upnp-org:device:SomethingElse:1"})
        responses = run_async(DISCOVER.search(resource, request, {}, {}, REMOTE, LOCAL))
        assert responses == ()

    def test_a_response_carries_the_targets_own_metadata(self):
        """A response includes the specific target's own stored metadata
        (e.g. `USN`), not just the search-generated headers."""
        device = DummyDevice("mydevice", udn=UDN)
        device_uri = URI.parse("/device.xml")
        upnp_device = UPnPDevice(device)
        resource = HTTPResponder({device_uri: upnp_device})

        request = HTTPRequest("SEARCH", STAR_PATH, {"ST": str(device.deviceType)})
        (response,) = run_async(DISCOVER.search(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.headers["USN"] == upnp_device.data[str(device.deviceType)]["USN"]

    def test_a_target_failing_an_unrelated_predicate_is_excluded(self):
        """A target satisfying `ST` but failing another predicate (e.g.
        `Accept`) is excluded."""
        collection = ResourceCollection(
            predicates={
                "ST": StringPredicate(["urn:test:device:Foo:1"]),
                "Accept": StringPredicate(["text/xml"]),
            },
            data={"urn:test:device:Foo:1": {"USN": "some-usn"}},
        )
        resource = HTTPResponder({URI.parse("/foo.xml"): collection})

        request = HTTPRequest("SEARCH", STAR_PATH, {"ST": "urn:test:device:Foo:1", "Accept": "text/plain"})
        responses = run_async(DISCOVER.search(resource, request, {}, {}, REMOTE, LOCAL))
        assert responses == ()

    def test_a_target_satisfying_every_predicate_is_still_included(self):
        """A target satisfying every predicate is included."""
        collection = ResourceCollection(
            predicates={
                "ST": StringPredicate(["urn:test:device:Foo:1"]),
                "Accept": StringPredicate(["text/xml"]),
            },
            data={"urn:test:device:Foo:1": {"USN": "some-usn"}},
        )
        resource = HTTPResponder({URI.parse("/foo.xml"): collection})

        request = HTTPRequest("SEARCH", STAR_PATH, {"ST": "urn:test:device:Foo:1", "Accept": "text/xml"})
        responses = run_async(DISCOVER.search(resource, request, {}, {}, REMOTE, LOCAL))
        assert len(responses) == 1

    def test_missing_st_header_matches_nothing(self):
        """A search with no `ST` header at all matches nothing."""
        device = DummyDevice("mydevice", udn=UDN)
        device_uri = URI.parse("/device.xml")
        resource = HTTPResponder({device_uri: UPnPDevice(device)})

        request = HTTPRequest("SEARCH", STAR_PATH)
        responses = run_async(DISCOVER.search(resource, request, {}, {}, REMOTE, LOCAL))
        assert responses == ()

    def test_response_headers_include_the_given_static_headers(self):
        """Every response includes the given static headers."""
        device = DummyDevice("mydevice", udn=UDN)
        device_uri = URI.parse("/device.xml")
        resource = HTTPResponder({device_uri: UPnPDevice(device)})

        request = HTTPRequest("SEARCH", STAR_PATH, {"ST": "ssdp:all"})
        responses = run_async(DISCOVER.search(resource, request, {}, {"Server": "gossip"}, REMOTE, LOCAL))
        assert all(response.headers["Server"] == "gossip" for response in responses)
