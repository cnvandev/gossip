from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

from gossip.http.message import HTTPRequest
from gossip.internet.predicate import StringPredicate
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.ssdp.extension import DISCOVER
from gossip.ssdp.responder import SSDPResponder

from ..support.resources import InMemoryResource

TARGET = URI.parse("/thing")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), 1900)


class TestSSDPResponderConstruction:
    """Building an `SSDPResponder` behaves exactly like the base
    `ExtendedHTTPResponder` it wraps - it only changes error handling."""

    def test_stores_extensions_and_static_headers_like_the_base_class(self):
        """`extensions`/`static_headers` are passed straight through to
        `ExtendedHTTPResponder.__init__()`."""
        responder = SSDPResponder({TARGET: InMemoryResource()}, [DISCOVER], static_headers={"X-Test": "yes"})
        assert responder.extensions == {DISCOVER.identifier: DISCOVER}
        assert responder.static_headers["X-Test"] == "yes"


class TestSSDPResponderUnidentifiable:
    """`SSDPResponder.unidentifiable()` never sends an error response -
    SSDP is broadcast on the network, so an error reply would just add
    noise every other listener has to filter out."""

    def test_returns_no_response_with_no_error(self):
        """No error at all still returns nothing, not the base
        responder's `404 Not Found`."""
        assert tuple(SSDPResponder({}).unidentifiable()) == ()

    def test_returns_no_response_with_an_error(self):
        """An error (that would normally pick a `400`) is swallowed the
        same way."""
        assert tuple(SSDPResponder({}).unidentifiable(ValueError("bad target"))) == ()


class TestSSDPResponderUnsatisfiable:
    """`SSDPResponder.unsatisfiable()` never sends an error response
    either, regardless of which constraint failed."""

    def test_returns_no_response(self):
        """A failed `Accept` constraint (which would normally pick a
        `415`) still returns nothing."""
        constraints = {"Accept": (None, {})}
        assert tuple(SSDPResponder({}).unsatisfiable(constraints)) == ()


class TestSSDPResponderUnknownMethod:
    """`SSDPResponder.unknown_method()` never sends an error response."""

    def test_returns_no_response(self):
        """Would normally pick a `405`; here it returns nothing."""
        assert tuple(SSDPResponder({}).unknown_method()) == ()


class TestSSDPResponderRespond:
    """End-to-end `respond()` (inherited from `HTTPResponder`/
    `ExtendedHTTPResponder`) - every error path SSDP hits comes back
    empty, while a successful request still gets a real response."""

    async def test_an_unidentified_target_gets_no_response(self):
        """A request for a resource that isn't registered gets nothing
        back, not a `404`."""
        responder = SSDPResponder({})
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/missing"))
        responses = await responder.respond(request, REMOTE, LOCAL)
        assert tuple(responses) == ()

    async def test_an_unsatisfiable_request_gets_no_response(self):
        """A request failing a resource's own predicate (e.g. `Accept`)
        gets nothing back, not a `415`."""
        resource = InMemoryResource(predicates={"Accept": StringPredicate(["text/xml"])})
        responder = SSDPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET, {"Accept": "text/plain"})
        responses = await responder.respond(request, REMOTE, LOCAL)
        assert tuple(responses) == ()

    async def test_an_unknown_method_gets_no_response(self):
        """A method neither the accessor nor any extension knows gets
        nothing back, not a `405`."""
        responder = SSDPResponder({TARGET: InMemoryResource()})
        request = HTTPRequest("TEAPOT", TARGET)
        responses = await responder.respond(request, REMOTE, LOCAL)
        assert tuple(responses) == ()

    async def test_a_successful_request_still_gets_a_real_response(self):
        """A satisfiable, identifiable, known-method request still gets
        a genuine response - only the error paths are silenced."""
        responder = SSDPResponder({TARGET: InMemoryResource(b"hi", {"Content-Type": "text/plain"})})
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert await response.body.read() == b"hi"
