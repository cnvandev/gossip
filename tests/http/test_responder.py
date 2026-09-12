from datetime import UTC, datetime
from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

from gossip.http.message import HTTPRequest
from gossip.http.predicate import StringPredicate
from gossip.http.responder import STAR_PATH, TIME_FORMAT, HTTPResponder
from gossip.internet.product import ProductStack
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader

from ..support.resources import InMemoryResource

TARGET = URI.parse("/thing")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), 80)


class TestHTTPResponderConstruction:
    """Building an `HTTPResponder` from its resources and optional
    accessor/headers/predicates."""

    def test_server_header_is_added_to_static_headers(self):
        """`Server` is always set, even with no `static_headers` given."""
        responder = HTTPResponder({})
        assert responder.static_headers == {
            "Server": str(ProductStack.gossip()),
        }

    def test_given_static_headers_are_kept_alongside_server(self):
        """Given static headers are kept, with `Server` added alongside."""
        responder = HTTPResponder({}, static_headers={"X-Custom": "yes"})
        assert responder.static_headers == {
            "X-Custom": "yes",
            "Server": str(ProductStack.gossip()),
        }

    def test_resources_include_the_responder_itself_at_the_star_path(self):
        """The `*` path resolves to the responder itself."""
        responder = HTTPResponder({})
        assert responder.resources == {STAR_PATH: responder}

    def test_resources_include_the_given_resources_too(self):
        """A resource registered under a URI is reachable at that URI."""
        resource = InMemoryResource()
        responder = HTTPResponder({TARGET: resource})
        assert responder.resources == {
            STAR_PATH: responder,
            TARGET: resource,
        }


class TestHTTPResponderRepr:
    """`HTTPResponder.__repr__()` - a compact summary naming the class, its
    resources, and its own `data`."""

    def test_includes_class_name_resources_and_data(self):
        """The rendered text names the class and includes `resources` and `data`."""
        resource = InMemoryResource()
        responder = HTTPResponder({TARGET: resource})
        text = repr(responder)
        assert text.startswith("<HTTPResponder,")
        assert "resources=" in text
        assert "data=" in text


class TestHTTPResponderDefaultHeaders:
    """`HTTPResponder.default_headers()` - the static headers plus a fresh
    `Date` for every response."""

    def test_includes_static_headers(self):
        """Every static header, including `Server`, is in the result."""
        responder = HTTPResponder({}, static_headers={"X-Custom": "yes"})
        headers = responder.default_headers()
        assert headers["X-Custom"] == "yes"
        assert headers["Server"] == str(ProductStack.gossip())

    def test_date_header_is_a_valid_rfc_format_timestamp(self):
        """`Date` is a well-formed RFC 9110 timestamp."""
        responder = HTTPResponder({})
        headers = responder.default_headers()
        datetime.strptime(headers["Date"], TIME_FORMAT).astimezone(UTC)


class TestHTTPResponderUnidentifiable:
    """`HTTPResponder.unidentifiable()` - classifies why no target resource
    was found, by the exception (if any) that occurred while looking."""

    def test_no_error_means_not_found(self):
        """With no exception given, the target simply wasn't found."""
        (response,) = HTTPResponder({}).unidentifiable()
        assert response.status == HTTPStatus.NOT_FOUND

    def test_value_error_means_bad_request(self):
        """A `ValueError` means the target URI itself was invalid."""
        (response,) = HTTPResponder({}).unidentifiable(ValueError())
        assert response.status == HTTPStatus.BAD_REQUEST

    def test_key_error_means_misdirected_request(self):
        """A `KeyError` means the URI was valid but its domain wasn't."""
        (response,) = HTTPResponder({}).unidentifiable(KeyError())
        assert response.status == HTTPStatus.MISDIRECTED_REQUEST


class TestHTTPResponderUnsatisfiable:
    """`HTTPResponder.unsatisfiable()` - classifies an unsatisfiable request
    by which header(s) it failed on."""

    def test_accept_failure_is_unsupported_media_type(self):
        """A failed `Accept` constraint maps to `415`."""
        constraints = {"Accept": (None, {})}
        (response,) = HTTPResponder({}).unsatisfiable(constraints)
        assert response.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    def test_authorization_failure_is_unauthorized(self):
        """A failed `Authorization` constraint maps to `401`."""
        constraints = {"Authorization": (None, {})}
        (response,) = HTTPResponder({}).unsatisfiable(constraints)
        assert response.status == HTTPStatus.UNAUTHORIZED

    def test_any_other_failure_is_precondition_failed(self):
        """Any other failed constraint maps to `412`."""
        constraints = {"Accept-Language": (None, {})}
        (response,) = HTTPResponder({}).unsatisfiable(constraints)
        assert response.status == HTTPStatus.PRECONDITION_FAILED


class TestHTTPResponderUnknownMethod:
    """`HTTPResponder.unknown_method()` - the flat `405` given for a method
    the accessor doesn't know how to handle at all."""

    def test_responds_method_not_allowed(self):
        """Always `405`."""
        (response,) = HTTPResponder({}).unknown_method()
        assert response.status == HTTPStatus.METHOD_NOT_ALLOWED


class TestHTTPResponderSubcollections:
    """The responder's resources, without the `*` self entry."""

    def test_excludes_the_star_path_entry(self):
        """The implicit `*`-path entry isn't reported as a subcollection."""
        resource = InMemoryResource()
        responder = HTTPResponder({TARGET: resource})
        assert responder.subcollections() == {TARGET: resource}


class TestHTTPResponderRepresent:
    """The responder's own `*`-path representation, which is always empty."""

    async def test_always_returns_no_body_and_no_metadata(self):
        """Always empty, regardless of the URI or constraints passed in."""
        responder = HTTPResponder({})
        result = await responder.represent(STAR_PATH, {})
        assert result == (None, {})


class TestHTTPResponderOptions:
    """`HTTPResponder.options()` - reports the accessor's methods as an
    `Allow` header."""

    async def test_allow_lists_every_method_the_accessor_handles(self):
        """`Allow` enumerates the accessor's own six standard methods."""
        responder = HTTPResponder({})
        result = await responder.options(STAR_PATH, {})
        assert result == {"Allow": "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"}


class TestHTTPResponderRespond:
    """`HTTPResponder.respond()` - the full request-handling pipeline:
    identify the target resource, check it can be represented under the
    request's constraints, and dispatch to the accessor."""

    async def test_unknown_target_is_reported_as_not_found(self):
        """A request for an unknown URI gets a plain `404`."""
        responder = HTTPResponder({})
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.NOT_FOUND

    async def test_a_lookup_error_is_reported_via_unidentifiable(self):
        """An error looking up the target is classified by exception type,
        the same as a missing target."""

        class RaisingResources(dict):
            def get(self, key, default=None):
                raise ValueError("malformed identifier")

        responder = HTTPResponder({})
        responder.resources = RaisingResources()
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.BAD_REQUEST

    async def test_no_responses_at_all_is_handled_without_erroring(self):
        """A subclass giving no response at all doesn't break `respond()`."""

        class SilentResponder(HTTPResponder):
            def unidentifiable(self, error=None):
                return ()

        responder = SilentResponder({})
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        responses = await responder.respond(request, REMOTE, LOCAL)
        assert tuple(responses) == ()

    async def test_a_known_target_is_dispatched_through_the_accessor(self):
        """A `GET` for a registered resource returns its representation."""
        resource = InMemoryResource(b"hi", {"Content-Type": "text/plain"})
        responder = HTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert await response.body.read() == b"hi"
        assert response.headers["Content-Type"] == "text/plain"

    async def test_response_headers_include_the_responders_default_headers(self):
        """Static headers and a fresh `Date` are merged into every response."""
        resource = InMemoryResource()
        responder = HTTPResponder({TARGET: resource}, static_headers={"X-Custom": "yes"})
        request = HTTPRequest(HTTPMethod.OPTIONS, TARGET)
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.headers["X-Custom"] == "yes"
        assert "Date" in response.headers

    async def test_an_ip_host_header_is_merged_into_a_netloc_less_targets_identifier(self):
        """A netloc-less target's identifier picks up an IP `Host` header."""
        located = URI.parse("/thing")._replace(netloc="239.255.255.250")
        resource = InMemoryResource()
        responder = HTTPResponder({located: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET, {"Host": "239.255.255.250"})
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.OK

    async def test_a_non_ip_host_header_does_not_change_the_lookup(self):
        """A hostname (rather than an IP) `Host` header is left as-is."""
        located = URI.parse("/thing")._replace(netloc="example.com")
        resource = InMemoryResource()
        responder = HTTPResponder({located: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET, {"Host": "example.com"})
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.NOT_FOUND

    async def test_a_target_with_its_own_netloc_ignores_the_host_header(self):
        """A target URI with its own netloc ignores the `Host` header."""
        full_target = URI.parse("http://example.com/thing")
        resource = InMemoryResource()
        responder = HTTPResponder({full_target: resource})
        request = HTTPRequest(HTTPMethod.GET, full_target, {"Host": "9.9.9.9"})
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.OK

    async def test_a_fully_rejected_header_is_reported_as_unsatisfiable(self):
        """A header matching none of the resource's options is rejected
        with the matching status, without reaching the accessor."""
        resource = InMemoryResource(b"hi", predicates={"Accept": StringPredicate(["text/plain"])})
        responder = HTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET, {"Accept": "application/json"})
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    async def test_a_satisfied_header_is_dispatched_normally(self):
        """A header matching one of the resource's options reaches its
        real representation."""
        resource = InMemoryResource(b"hi", predicates={"Accept": StringPredicate(["text/plain"])})
        responder = HTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.GET, TARGET, {"Accept": "text/plain"})
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert await response.body.read() == b"hi"

    async def test_trace_echoes_the_request_body_back(self):
        """`TRACE` sends the request's body back as `message/http`."""
        body = BufferedReader.for_bytes(b"echo me")
        resource = InMemoryResource()
        responder = HTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.TRACE, TARGET, body=body)
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.OK
        assert response.body is body
        assert response.headers["Content-Type"] == "message/http"

    async def test_trace_with_content_length_is_rejected(self):
        """RFC 9110 §9.3.8: a `TRACE` request must not carry content."""
        resource = InMemoryResource()
        responder = HTTPResponder({TARGET: resource})
        request = HTTPRequest(HTTPMethod.TRACE, TARGET, {"Content-Length": "4"})
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.BAD_REQUEST

    async def test_an_unknown_method_is_reported_as_not_allowed(self):
        """A method with no handler at all gets a plain `405`."""
        resource = InMemoryResource()
        responder = HTTPResponder({TARGET: resource})
        request = HTTPRequest("FROBNICATE", TARGET)
        (response,) = await responder.respond(request, REMOTE, LOCAL)
        assert response.status == HTTPStatus.METHOD_NOT_ALLOWED
