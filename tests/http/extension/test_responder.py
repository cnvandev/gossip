from asyncio import run as run_async
from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

from gossip.http.extension.framework import Extension
from gossip.http.extension.responder import ExtendedHTTPResponder
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.responder import HTTPResponder
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint

from ...support.resources import InMemoryResource

TARGET = URI.parse("/thing")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), 80)


async def search_handler(resource, request, constraints, headers, remote, local):
    return (HTTPResponse(HTTPStatus.OK, dict(headers) | {"X-Handled": "search"}),)


async def move_handler(resource, request, constraints, headers, remote, local):
    return (HTTPResponse(HTTPStatus.OK, dict(headers) | {"X-Handled": "move"}),)


class TestExtendedHTTPResponderConstruction:
    """Building an `ExtendedHTTPResponder`, keyed by each extension's own
    `identifier`."""

    def test_extensions_are_keyed_by_identifier(self):
        """Each given extension is reachable by its own `identifier`."""
        extension = Extension("my-ext")
        responder = ExtendedHTTPResponder({}, [extension])
        assert responder.extensions == {"my-ext": extension}

    def test_defaults_to_no_extensions(self):
        """Omitting `extensions` leaves the responder with none at all."""
        assert ExtendedHTTPResponder({}).extensions == {}


class TestExtendedHTTPResponderOptions:
    """`ExtendedHTTPResponder.options()` - the `Allow` header, widened to
    include every method any registered extension adds."""

    def test_allow_includes_the_standard_methods_with_no_extensions(self):
        """With no extensions, `Allow` matches a plain `HTTPResponder`."""
        responder = ExtendedHTTPResponder({})
        expected = run_async(HTTPResponder({}).options(TARGET, {}))
        result = run_async(responder.options(TARGET, {}))
        assert expected == result

    def test_allow_includes_an_extensions_own_methods_too(self):
        """A custom method an extension adds shows up in `Allow` too."""
        extension = Extension("my-ext", methods={"SEARCH": search_handler})
        responder = ExtendedHTTPResponder({}, [extension])
        result = run_async(responder.options(TARGET, {}))
        allowed = set(result["Allow"].split(", "))
        assert "SEARCH" in allowed
        assert "GET" in allowed


class TestExtendedHTTPResponderSuccessful:
    """On top of the base responder's dispatch, `successful()` checks the
    request's declared extensions, rejecting an unknown mandatory one and
    routing a known one's methods through the extension itself."""

    def test_an_unknown_mandatory_extension_is_rejected(self):
        """An unknown `Man`-declared extension gets `510 Not Extended`."""
        resource = InMemoryResource()
        responder = ExtendedHTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET, {"Man": "unknown-ext; ns=1"})
        (response,) = run_async(responder.successful(resource, request, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.NOT_EXTENDED

    def test_a_known_mandatory_extension_strips_the_m_prefix_and_dispatches_to_it(self):
        """A known extension's `M-`-prefixed method is stripped and routed
        to that extension's handler."""
        extension = Extension("my-ext", methods={"SEARCH": search_handler})
        resource = InMemoryResource()
        responder = ExtendedHTTPResponder({TARGET: resource}, [extension])
        request = HTTPRequest("M-SEARCH", TARGET, {"Man": "my-ext; ns=1"})
        (response,) = run_async(responder.successful(resource, request, {}, REMOTE, LOCAL))
        assert response.headers["X-Handled"] == "search"
        assert response.headers["Ext"] == ""

    def test_no_declared_extension_falls_through_to_the_base_responder(self):
        """With no extension declared, dispatch falls through to the
        plain `HTTPResponder` behavior."""
        resource = InMemoryResource(b"hi", {"Content-Type": "text/plain"})
        responder = ExtendedHTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = run_async(responder.successful(resource, request, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert run_async(response.body.read()) == b"hi"
        assert response.headers["Content-Type"] == "text/plain"

    def test_connect_still_falls_through_to_the_base_responders_handling(self):
        """`CONNECT` still falls through to the base responder's handling."""
        resource = InMemoryResource()
        responder = ExtendedHTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.CONNECT, TARGET)
        responses = run_async(responder.successful(resource, request, {}, REMOTE, LOCAL))
        assert tuple(responses) == ()

    def test_a_uri_identified_extension_is_matched_by_its_quoted_declaration(self):
        """A URI identifier is matched via its quoted declaration."""
        identifier = URI.parse("ssdp:discover")
        extension = Extension(identifier, methods={"SEARCH": search_handler})
        resource = InMemoryResource()
        responder = ExtendedHTTPResponder({TARGET: resource}, [extension])
        request = HTTPRequest("M-SEARCH", TARGET, {"Man": '"ssdp:discover"; ns=1'})
        (response,) = run_async(responder.successful(resource, request, {}, REMOTE, LOCAL))
        assert response.headers["X-Handled"] == "search"

    def test_an_optional_declaration_does_not_mangle_an_m_prefixed_method_name(self):
        """An `Opt`-only declaration leaves an `M`-prefixed method name intact."""
        extension = Extension("opt-ext", methods={"MOVE": move_handler})
        resource = InMemoryResource()
        responder = ExtendedHTTPResponder({TARGET: resource}, [extension])
        request = HTTPRequest("MOVE", TARGET, {"Opt": "opt-ext; ns=1"})
        (response,) = run_async(responder.successful(resource, request, {}, REMOTE, LOCAL))
        assert response.headers["X-Handled"] == "move"
