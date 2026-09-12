from asyncio import run as run_async
from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

from gossip.http.accessor import HTTPAccessor
from gossip.http.message import HTTPRequest
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader

from ..support.resources import InMemoryResource

TARGET = URI.parse("/foo")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), 80)


class TestHTTPAccessorOptions:
    """`OPTIONS` - reports the resource's representation options, with no
    body."""

    def test_reports_the_resources_allowed_methods_with_no_body(self):
        """The resource's options become the `Allow` header, with no body."""
        resource = InMemoryResource()
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.OPTIONS, TARGET)
        (response,) = run_async(accessor.access(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.OK
        assert response.headers["Allow"] == "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"
        assert response.body is None

    def test_static_headers_win_over_resource_options_on_conflict(self):
        """A static header overrides a resource option of the same name."""
        resource = InMemoryResource()
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.OPTIONS, TARGET)
        (response,) = run_async(accessor.access(resource, request, {}, {"Allow": "GET"}, REMOTE, LOCAL))
        assert response.headers["Allow"] == "GET"


class TestHTTPAccessorHead:
    """`HEAD` - represents the resource for its metadata, discarding the
    body entirely."""

    def test_returns_metadata_with_no_body(self):
        """`HEAD` returns the same metadata `GET` would, but no body."""
        resource = InMemoryResource(b"hello", {"Content-Length": "5"})
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.HEAD, TARGET)
        (response,) = run_async(accessor.access(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.OK
        assert response.headers["Content-Length"] == "5"
        assert response.body is None


class TestHTTPAccessorGet:
    """`GET` - represents the resource, this time keeping the body."""

    def test_returns_the_resources_actual_stored_representation(self):
        """`GET` returns the resource's actual stored body and metadata."""
        resource = InMemoryResource(b"hello", {"Content-Type": "text/plain"})
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        constraints = {"Accept": ("text/plain", {})}
        (response,) = run_async(accessor.access(resource, request, constraints, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert run_async(response.body.read()) == b"hello"
        assert response.headers["Content-Type"] == "text/plain"

    def test_static_headers_win_over_resource_metadata_on_conflict(self):
        """A static header overrides a resource metadata entry of the same name."""
        resource = InMemoryResource(b"hello", {"Server": "resource"})
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = run_async(accessor.access(resource, request, {}, {"Server": "static"}, REMOTE, LOCAL))
        assert response.headers["Server"] == "static"


class TestHTTPAccessorPut:
    """`PUT` - writes the request body to the resource, replacing
    whatever it held before."""

    def test_overwrites_the_resource_with_the_request_body(self):
        """`PUT` replaces the resource's stored body with the request body."""
        resource = InMemoryResource(b"old content")
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.PUT, TARGET, body=BufferedReader.for_bytes(b"new content"))
        (response,) = run_async(accessor.access(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert run_async(response.body.read()) == b"new content"
        assert resource.body == b"new content"


class TestHTTPAccessorPatch:
    """`PATCH` - sends the request body to the resource as a partial
    update."""

    def test_updates_the_resource_and_returns_the_result(self):
        """`PATCH` appends the patch body, and the response reflects it."""
        resource = InMemoryResource(b"hello ")
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.PATCH, TARGET, body=BufferedReader.for_bytes(b"world"))
        (response,) = run_async(accessor.access(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.OK
        assert response.body is not None
        assert run_async(response.body.read()) == b"hello world"
        assert resource.body == b"hello world"


class TestHTTPAccessorDelete:
    """`DELETE` - clears the resource's data, responding `204 No Content`
    even though a body (whatever was just deleted) comes back too."""

    def test_clears_the_resource_and_responds_no_content(self):
        """`DELETE` empties the resource and responds `204 No Content`."""
        resource = InMemoryResource(b"to be deleted")
        accessor = HTTPAccessor()
        request = HTTPRequest(HTTPMethod.DELETE, TARGET)
        (response,) = run_async(accessor.access(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.status == HTTPStatus.NO_CONTENT
        assert response.body is not None
        assert run_async(response.body.read()) == b"to be deleted"
        assert resource.body == b""
