from asyncio import StreamReader
from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

import pytest

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.product import Product
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader

from ..support.streams import FakeStreamWriter

ENDPOINT = Endpoint(IPv4Address("127.0.0.1"), 80)


class TestHTTPRequestTrailers:
    """`HTTPRequest.trailers`/`wait_trailers()` - the RFC 9112 trailer
    section, either supplied upfront or parsed off the body once it's
    been read to EOF."""

    def test_defaults_to_none_and_needs_no_running_event_loop(self):
        """Defaults to `None`, without needing a running event loop."""
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"))
        assert request.trailers is None

    def test_a_plain_mapping_is_stored_immediately(self):
        """An explicit `trailers` mapping is available immediately."""
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"), trailers={"X-Checksum": "abc"})
        assert request.trailers is not None
        assert request.trailers.to_dict() == {"X-Checksum": "abc"}

    async def test_wait_trailers_returns_a_plain_mapping_without_reading_anything(self):
        """Given trailers upfront, `wait_trailers()` just returns them."""
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"), trailers={"X-Checksum": "abc"})
        trailers = await request.wait_trailers()
        assert trailers is not None
        assert trailers.to_dict() == {"X-Checksum": "abc"}

    async def test_wait_trailers_drains_body_when_not_given_upfront(self):
        """With no explicit trailers, reads `body` to EOF and parses it."""
        body = BufferedReader.for_bytes(b"X-Checksum: abc\r\n\r\n")
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"), body=body)
        trailers = await request.wait_trailers()
        assert trailers is not None
        assert trailers.to_dict() == {"X-Checksum": "abc"}


class TestHTTPRequestConstruction:
    """Building an `HTTPRequest` from a method, target, and optional
    headers/body/protocol."""

    def test_defaults_to_no_headers_and_no_body(self):
        """Omitting headers/body leaves an empty header map and no body."""
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"))
        assert dict(request.headers) == {}
        assert request.body is None

    def test_method_keeps_its_original_casing(self):
        """`method` preserves the casing it was given."""
        request = HTTPRequest("get", URI.parse("/foo"))
        assert request.method == "get"

    def test_wire_form_upper_cases_the_method_regardless_of_input_casing(self):
        """The wire form's method is always upper-cased."""
        request = HTTPRequest("get", URI.parse("/foo"))
        assert bytes(request).startswith(b"GET /foo HTTP/1.1\r\n")

    def test_default_protocol_is_http_1_1(self):
        """Omitting a protocol defaults to HTTP/1.1."""
        assert HTTPRequest(HTTPMethod.GET, URI.parse("/foo")).protocol == Product("HTTP", "1.1")


class TestHTTPRequestSerialization:
    """Serializing an `HTTPRequest` to wire bytes: `METHOD target PROTOCOL`
    followed by headers and an optional body."""

    def test_bytes_appends_the_protocol_to_the_start_line(self):
        """The wire form has the protocol as a third token."""
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"), {"Host": "example.com"})
        assert bytes(request) == b"GET /foo HTTP/1.1\r\nHost: example.com\r\n\r\n"

    def test_bytes_raises_for_a_request_with_a_body(self):
        """`bytes()` refuses a request with a body; use `write_to()` instead."""
        request = HTTPRequest(HTTPMethod.POST, URI.parse("/foo"), body=BufferedReader.for_bytes(b"hi"))
        with pytest.raises(ValueError):
            bytes(request)

    def test_repr_is_the_start_line_with_protocol(self):
        """`repr()` shows the wire form's start line."""
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"))
        assert repr(request) == "GET /foo HTTP/1.1"


class TestHTTPRequestWriteTo:
    """Streaming an `HTTPRequest` to a writer - unlike `bytes()`, this
    supports a body."""

    async def test_writes_a_request_with_a_body(self):
        """A request with a body streams correctly via `write_to()`."""
        request = HTTPRequest(HTTPMethod.POST, URI.parse("/foo"), {"Host": "example.com", "Content-Length": "2"}, body=BufferedReader.for_bytes(b"hi"))
        writer = FakeStreamWriter()
        await request.write_to(writer)
        assert bytes(writer.buffer) == b"POST /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 2\r\n\r\nhi"

    async def test_matches_bytes_for_a_headers_only_request(self):
        """For a headers-only request, matches what `bytes()` produces."""
        request = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"), {"Host": "example.com"})
        writer = FakeStreamWriter()
        await request.write_to(writer)
        assert bytes(writer.buffer) == bytes(request)


class TestHTTPRequestReadFrom:
    """Parsing an `HTTPRequest` back from wire bytes."""

    async def test_round_trips_a_headers_only_request(self):
        """A serialized headers-only request parses back to an equivalent one."""
        original = HTTPRequest(HTTPMethod.GET, URI.parse("/foo"), {"Host": "example.com"})
        parsed = await HTTPRequest.read_from((bytes(original), ENDPOINT))
        assert parsed is not None
        assert parsed.method == "GET"
        assert parsed.target == URI.parse("/foo")
        assert dict(parsed.headers) == {"Host": "example.com"}
        assert parsed.protocol == Product("HTTP", "1.1")

    async def test_the_tuple_form_never_carries_a_body(self):
        """A request parsed from `(bytes, Endpoint)` never gets a body."""
        data = b"GET /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 2\r\n\r\nhi"
        parsed = await HTTPRequest.read_from((data, ENDPOINT))
        assert parsed is not None
        assert parsed.body is None

    async def test_reads_from_a_live_stream_reader_too(self):
        """A real `StreamReader` works the same as the `(bytes, Endpoint)` form."""
        reader = StreamReader()
        reader.feed_data(bytes(HTTPRequest(HTTPMethod.GET, URI.parse("/foo"))))
        reader.feed_eof()
        parsed = await HTTPRequest.read_from(reader)
        assert parsed is not None
        assert parsed.method == "GET"

    async def test_body_is_the_reader_itself_when_read_from_a_stream(self):
        """A request parsed off a live stream gets the reader as `body`."""
        reader = StreamReader()
        reader.feed_data(b"POST /foo HTTP/1.1\r\nContent-Length: 2\r\n\r\nhi")
        reader.feed_eof()
        request = await HTTPRequest.read_from(reader)
        assert request is not None
        assert request.body is reader

    async def test_rejects_a_non_http_protocol(self):
        """A start line naming a different protocol is refused."""
        data = b"GET /foo SPDY/1.1\r\nHost: example.com\r\n\r\n"
        assert await HTTPRequest.read_from((data, ENDPOINT)) is None

    async def test_chunked_body_is_decoded(self):
        """A `Transfer-Encoding: chunked` body is decoded by the time it
        reaches `body`."""
        reader = StreamReader()
        reader.feed_data(b"POST /foo HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n")
        reader.feed_eof()
        request = await HTTPRequest.read_from(reader)
        assert request is not None
        assert request.body is not None
        assert await request.body.read() == b"hello"

    async def test_invalid_transfer_encoding_is_rejected(self):
        """An undecodable coding is refused outright."""
        reader = StreamReader()
        reader.feed_data(b"POST /foo HTTP/1.1\r\nTransfer-Encoding: compress\r\n\r\ngarbage")
        reader.feed_eof()
        assert await HTTPRequest.read_from(reader) is None

    async def test_returns_none_for_a_start_line_missing_parts(self):
        """An incomplete start line fails cleanly with `None`."""
        data = b"JUSTONEWORD\r\nHost: example.com\r\n\r\n"
        assert await HTTPRequest.read_from((data, ENDPOINT)) is None

    async def test_returns_none_for_unparseable_underlying_message(self):
        """An unparseable buffer (e.g. empty) returns `None`."""
        assert await HTTPRequest.read_from((b"", ENDPOINT)) is None


class TestHTTPResponseConstruction:
    """Building an `HTTPResponse` from a status and optional
    headers/body/protocol."""

    def test_default_protocol_is_http_1_1(self):
        """Omitting a protocol defaults to HTTP/1.1."""
        assert HTTPResponse(HTTPStatus.OK).protocol == Product("HTTP", "1.1")


class TestHTTPResponseSerialization:
    """Serializing an `HTTPResponse` to wire bytes: `PROTOCOL code phrase`
    followed by headers and an optional body."""

    def test_bytes_prepends_the_protocol_to_the_start_line(self):
        """A response's wire form leads with the protocol."""
        response = HTTPResponse(HTTPStatus.OK, {"Content-Type": "text/plain"})
        assert bytes(response) == b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n"

    def test_bytes_raises_for_a_response_with_a_body(self):
        """`bytes()` refuses a response with a body."""
        response = HTTPResponse(HTTPStatus.OK, body=BufferedReader.for_bytes(b"hi"))
        with pytest.raises(ValueError):
            bytes(response)

    def test_repr_is_the_protocol_and_start_line(self):
        """`repr()` shows the wire form's start line."""
        assert repr(HTTPResponse(HTTPStatus.OK)) == "HTTP/1.1 200 OK"


class TestHTTPResponseWriteTo:
    """Streaming an `HTTPResponse` to a writer - unlike `bytes()`, this
    supports a body."""

    async def test_writes_a_response_with_a_body(self):
        """A response with a body streams correctly via `write_to()`."""
        response = HTTPResponse(HTTPStatus.OK, {"Content-Length": "2"}, body=BufferedReader.for_bytes(b"hi"))
        writer = FakeStreamWriter()
        await response.write_to(writer)
        assert bytes(writer.buffer) == b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"

    async def test_matches_bytes_for_a_headers_only_response(self):
        """For a headers-only response, matches what `bytes()` produces."""
        response = HTTPResponse(HTTPStatus.NO_CONTENT)
        writer = FakeStreamWriter()
        await response.write_to(writer)
        assert bytes(writer.buffer) == bytes(response)


class TestHTTPResponseReadFrom:
    """Parsing an `HTTPResponse` back from wire bytes."""

    async def test_round_trips_a_headers_only_response(self):
        """A serialized headers-only response parses back to an equivalent one."""
        original = HTTPResponse(HTTPStatus.NOT_FOUND)
        parsed = await HTTPResponse.read_from((bytes(original), ENDPOINT))
        assert parsed is not None
        assert parsed.status == HTTPStatus.NOT_FOUND
        assert parsed.protocol == Product("HTTP", "1.1")

    async def test_the_tuple_form_never_carries_a_body(self):
        """A response parsed from `(bytes, Endpoint)` never gets a body."""
        data = b"HTTP/1.1 404 Not Found\r\nContent-Length: 7\r\n\r\nmissing"
        parsed = await HTTPResponse.read_from((data, ENDPOINT))
        assert parsed is not None
        assert parsed.body is None

    async def test_reads_from_a_live_stream_reader_too(self):
        """A real `StreamReader` works the same as the `(bytes, Endpoint)` form."""
        reader = StreamReader()
        reader.feed_data(bytes(HTTPResponse(HTTPStatus.OK)))
        reader.feed_eof()
        parsed = await HTTPResponse.read_from(reader)
        assert parsed is not None
        assert parsed.status == HTTPStatus.OK

    async def test_body_is_the_reader_itself_when_read_from_a_stream(self):
        """A response parsed off a live stream gets the reader as `body`."""
        reader = StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\nmissing")
        reader.feed_eof()
        response = await HTTPResponse.read_from(reader)
        assert response is not None
        assert response.body is reader

    async def test_rejects_a_non_http_protocol(self):
        """A start line naming a different protocol is refused."""
        data = b"SPDY/1.1 200 OK\r\n\r\n"
        assert await HTTPResponse.read_from((data, ENDPOINT)) is None

    async def test_returns_none_for_a_start_line_missing_parts(self):
        """An incomplete start line fails cleanly with `None`."""
        data = b"HTTP/1.1\r\n\r\n"
        assert await HTTPResponse.read_from((data, ENDPOINT)) is None

    async def test_returns_none_for_unparseable_underlying_message(self):
        """An unparseable buffer (e.g. empty) returns `None`."""
        assert await HTTPResponse.read_from((b"", ENDPOINT)) is None

    async def test_chunked_body_is_decoded(self):
        """A `Transfer-Encoding: chunked` body is decoded by the time it
        reaches `body`."""
        reader = StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n")
        reader.feed_eof()
        response = await HTTPResponse.read_from(reader)
        assert response is not None
        assert response.body is not None
        assert await response.body.read() == b"hello"

    async def test_invalid_transfer_encoding_is_rejected(self):
        """An undecodable coding is refused outright."""
        reader = StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: compress\r\n\r\ngarbage")
        reader.feed_eof()
        assert await HTTPResponse.read_from(reader) is None
