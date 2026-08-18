from asyncio import StreamReader
from asyncio import run as run_async
from http import HTTPStatus
from ipaddress import IPv4Address

import pytest

from gossip.http.message import HTTPMessage, HTTPRequest, HTTPResponse
from gossip.internet.product import Product
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader

from ..support.streams import FakeStreamWriter

ENDPOINT = Endpoint(IPv4Address("127.0.0.1"), 80)


class TestHTTPMessageSerialization:
    """`HTTPMessage` itself provides the shared `bytes()`/`write_to()`
    machinery, but leaves turning a message into an `InternetMessage` to
    its subclasses."""

    def test_bytes_raises_without_a_subclass_implementation(self):
        """A bare `HTTPMessage` (as opposed to `HTTPRequest`/`HTTPResponse`)
        has no `_as_internet_message()` of its own, so serializing it
        raises rather than silently producing nothing."""
        message = HTTPMessage(("start",), {})
        with pytest.raises(NotImplementedError):
            bytes(message)


class TestHTTPRequestConstruction:
    """Building an `HTTPRequest` from a method, target, and optional
    headers/body/protocol."""

    def test_defaults_to_no_headers_and_no_body(self):
        """Omitting headers/body leaves an empty header map and no body."""
        request = HTTPRequest("GET", URI.parse("/foo"))
        assert dict(request.headers) == {}
        assert request.body is None

    def test_method_keeps_its_original_casing(self):
        """The `method` attribute preserves exactly what was passed in -
        only the wire form (`start_line`) is upper-cased."""
        request = HTTPRequest("get", URI.parse("/foo"))
        assert request.method == "get"

    def test_start_line_is_upper_cased_method_and_target(self):
        """The start line is `(METHOD, target)`, method upper-cased."""
        request = HTTPRequest("get", URI.parse("/foo"))
        assert request.start_line == ("GET", "/foo")

    def test_default_protocol_is_http_1_1(self):
        """Omitting a protocol defaults to HTTP/1.1."""
        assert HTTPRequest("GET", URI.parse("/foo")).protocol == Product("HTTP", "1.1")


class TestHTTPRequestSerialization:
    """Serializing an `HTTPRequest` to wire bytes: `METHOD target PROTOCOL`
    followed by headers and an optional body."""

    def test_bytes_appends_the_protocol_to_the_start_line(self):
        """Unlike `start_line` itself, the serialized wire form has the
        protocol appended as a third token."""
        request = HTTPRequest("GET", URI.parse("/foo"), {"Host": "example.com"})
        assert bytes(request) == b"GET /foo HTTP/1.1\r\nHost: example.com\r\n\r\n"

    def test_bytes_raises_for_a_request_with_a_body(self):
        """`bytes()` only supports headers-only requests (e.g. `HEAD`) -
        a request with a body has to be sent via `write_to()` instead,
        same as the underlying `InternetMessage`."""
        request = HTTPRequest("POST", URI.parse("/foo"), body=BufferedReader.for_bytes(b"hi"))
        with pytest.raises(ValueError):
            bytes(request)

    def test_repr_is_the_start_line_with_protocol(self):
        """`repr()` shows the same content as the start of the wire form."""
        request = HTTPRequest("GET", URI.parse("/foo"))
        assert repr(request) == "GET /foo HTTP/1.1"


class TestHTTPRequestWriteTo:
    """Streaming an `HTTPRequest` to a writer - unlike `bytes()`, this
    supports a body."""

    def test_writes_a_request_with_a_body(self):
        """A request with a body, which `bytes()` would refuse, streams
        correctly via `write_to()`. Content-Length isn't computed
        automatically - it's sent as-given, like any other header."""
        request = HTTPRequest("POST", URI.parse("/foo"), {"Host": "example.com", "Content-Length": "2"}, body=BufferedReader.for_bytes(b"hi"))
        writer = FakeStreamWriter()
        run_async(request.write_to(writer))
        assert bytes(writer.buffer) == b"POST /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 2\r\n\r\nhi"

    def test_matches_bytes_for_a_headers_only_request(self):
        """For a headers-only request, `write_to()` produces the same
        bytes `bytes()` would."""
        request = HTTPRequest("GET", URI.parse("/foo"), {"Host": "example.com"})
        writer = FakeStreamWriter()
        run_async(request.write_to(writer))
        assert bytes(writer.buffer) == bytes(request)


class TestHTTPRequestReadFrom:
    """Parsing an `HTTPRequest` back from wire bytes."""

    def test_round_trips_a_headers_only_request(self):
        """A headers-only request serialized with `bytes()` parses back to
        an equivalent request."""
        original = HTTPRequest("GET", URI.parse("/foo"), {"Host": "example.com"})
        parsed = run_async(HTTPRequest.read_from((bytes(original), ENDPOINT)))
        assert parsed is not None
        assert parsed.method == "GET"
        assert parsed.target == URI.parse("/foo")
        assert dict(parsed.headers) == {"Host": "example.com"}
        assert parsed.protocol == Product("HTTP", "1.1")

    def test_the_tuple_form_never_carries_a_body(self):
        """A request parsed from an in-memory `(bytes, Endpoint)` pair
        never gets a body - even with a `Content-Length` header and
        body-shaped bytes sitting right there in the buffer. A body
        requires an actual connection, by design; nothing forces one into
        a single UDP datagram."""
        data = b"GET /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 2\r\n\r\nhi"
        parsed = run_async(HTTPRequest.read_from((data, ENDPOINT)))
        assert parsed is not None
        assert parsed.body is None

    def test_reads_from_a_live_stream_reader_too(self):
        """The other accepted input, a real `asyncio.StreamReader`, works
        the same way as the `(bytes, Endpoint)` form."""

        async def read_it() -> HTTPRequest | None:
            reader = StreamReader()
            reader.feed_data(bytes(HTTPRequest("GET", URI.parse("/foo"))))
            reader.feed_eof()
            return await HTTPRequest.read_from(reader)

        parsed = run_async(read_it())
        assert parsed is not None
        assert parsed.method == "GET"

    def test_body_is_the_reader_itself_when_read_from_a_stream(self):
        """Unlike the tuple form, a request parsed off a live stream gets
        the reader itself as `body` - the body hasn't been read yet, and
        it's on the caller to pull it (using Content-Length from headers)."""

        async def read_it() -> tuple[HTTPRequest, StreamReader]:
            reader = StreamReader()
            reader.feed_data(b"POST /foo HTTP/1.1\r\nContent-Length: 2\r\n\r\nhi")
            reader.feed_eof()
            request = await HTTPRequest.read_from(reader)
            return request, reader

        request, reader = run_async(read_it())
        assert request is not None
        assert request.body is reader

    def test_rejects_a_non_http_protocol(self):
        """A start line naming a different protocol is refused, not
        misparsed as if it were HTTP."""
        data = b"GET /foo SPDY/1.1\r\nHost: example.com\r\n\r\n"
        assert run_async(HTTPRequest.read_from((data, ENDPOINT))) is None

    def test_returns_none_for_a_start_line_missing_parts(self):
        """A start line without all three of method/target/protocol fails
        cleanly with `None`."""
        data = b"JUSTONEWORD\r\nHost: example.com\r\n\r\n"
        assert run_async(HTTPRequest.read_from((data, ENDPOINT))) is None

    def test_returns_none_for_unparseable_underlying_message(self):
        """When the underlying `InternetMessage` itself can't be parsed
        (e.g. an empty buffer), that `None` propagates."""
        assert run_async(HTTPRequest.read_from((b"", ENDPOINT))) is None


class TestHTTPResponseConstruction:
    """Building an `HTTPResponse` from a status and optional
    headers/body/protocol."""

    def test_start_line_is_status_code_and_phrase(self):
        """The start line is `(code, phrase)`, both as strings."""
        response = HTTPResponse(HTTPStatus.NOT_FOUND)
        assert response.start_line == ("404", "Not Found")

    def test_default_protocol_is_http_1_1(self):
        """Omitting a protocol defaults to HTTP/1.1."""
        assert HTTPResponse(HTTPStatus.OK).protocol == Product("HTTP", "1.1")


class TestHTTPResponseSerialization:
    """Serializing an `HTTPResponse` to wire bytes: `PROTOCOL code phrase`
    followed by headers and an optional body."""

    def test_bytes_prepends_the_protocol_to_the_start_line(self):
        """Unlike a request (protocol last), a response's wire form leads
        with the protocol."""
        response = HTTPResponse(HTTPStatus.OK, {"Content-Type": "text/plain"})
        assert bytes(response) == b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n"

    def test_bytes_raises_for_a_response_with_a_body(self):
        """`bytes()` only supports headers-only responses - one with a
        body has to be sent via `write_to()` instead."""
        response = HTTPResponse(HTTPStatus.OK, body=BufferedReader.for_bytes(b"hi"))
        with pytest.raises(ValueError):
            bytes(response)

    def test_repr_is_the_protocol_and_start_line(self):
        """`repr()` shows the same content as the start of the wire form."""
        assert repr(HTTPResponse(HTTPStatus.OK)) == "HTTP/1.1 200 OK"


class TestHTTPResponseWriteTo:
    """Streaming an `HTTPResponse` to a writer - unlike `bytes()`, this
    supports a body."""

    def test_writes_a_response_with_a_body(self):
        """A response with a body, which `bytes()` would refuse, streams
        correctly via `write_to()`. Content-Length isn't computed
        automatically - it's sent as-given, like any other header."""
        response = HTTPResponse(HTTPStatus.OK, {"Content-Length": "2"}, body=BufferedReader.for_bytes(b"hi"))
        writer = FakeStreamWriter()
        run_async(response.write_to(writer))
        assert bytes(writer.buffer) == b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"

    def test_matches_bytes_for_a_headers_only_response(self):
        """For a headers-only response, `write_to()` produces the same
        bytes `bytes()` would."""
        response = HTTPResponse(HTTPStatus.NO_CONTENT)
        writer = FakeStreamWriter()
        run_async(response.write_to(writer))
        assert bytes(writer.buffer) == bytes(response)


class TestHTTPResponseReadFrom:
    """Parsing an `HTTPResponse` back from wire bytes."""

    def test_round_trips_a_headers_only_response(self):
        """A headers-only response serialized with `bytes()` parses back
        to an equivalent response, with the status recovered as an
        `HTTPStatus`."""
        original = HTTPResponse(HTTPStatus.NOT_FOUND)
        parsed = run_async(HTTPResponse.read_from((bytes(original), ENDPOINT)))
        assert parsed is not None
        assert parsed.status == HTTPStatus.NOT_FOUND
        assert parsed.protocol == Product("HTTP", "1.1")

    def test_the_tuple_form_never_carries_a_body(self):
        """A response parsed from an in-memory `(bytes, Endpoint)` pair
        never gets a body - even with a `Content-Length` header and
        body-shaped bytes sitting right there in the buffer. A body
        requires an actual connection, by design; nothing forces one into
        a single UDP datagram."""
        data = b"HTTP/1.1 404 Not Found\r\nContent-Length: 7\r\n\r\nmissing"
        parsed = run_async(HTTPResponse.read_from((data, ENDPOINT)))
        assert parsed is not None
        assert parsed.body is None

    def test_reads_from_a_live_stream_reader_too(self):
        """The other accepted input, a real `asyncio.StreamReader`, works
        the same way as the `(bytes, Endpoint)` form."""

        async def read_it() -> HTTPResponse | None:
            reader = StreamReader()
            reader.feed_data(bytes(HTTPResponse(HTTPStatus.OK)))
            reader.feed_eof()
            return await HTTPResponse.read_from(reader)

        parsed = run_async(read_it())
        assert parsed is not None
        assert parsed.status == HTTPStatus.OK

    def test_body_is_the_reader_itself_when_read_from_a_stream(self):
        """Unlike the tuple form, a response parsed off a live stream gets
        the reader itself as `body` - the body hasn't been read yet, and
        it's on the caller to pull it (using Content-Length from headers)."""

        async def read_it() -> tuple[HTTPResponse, StreamReader]:
            reader = StreamReader()
            reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\nmissing")
            reader.feed_eof()
            response = await HTTPResponse.read_from(reader)
            return response, reader

        response, reader = run_async(read_it())
        assert response is not None
        assert response.body is reader

    def test_rejects_a_non_http_protocol(self):
        """A start line naming a different protocol is refused."""
        data = b"SPDY/1.1 200 OK\r\n\r\n"
        assert run_async(HTTPResponse.read_from((data, ENDPOINT))) is None

    def test_returns_none_for_a_start_line_missing_parts(self):
        """A start line without all three of protocol/code/phrase fails
        cleanly with `None`."""
        data = b"HTTP/1.1\r\n\r\n"
        assert run_async(HTTPResponse.read_from((data, ENDPOINT))) is None

    def test_returns_none_for_unparseable_underlying_message(self):
        """When the underlying `InternetMessage` itself can't be parsed
        (e.g. an empty buffer), that `None` propagates."""
        assert run_async(HTTPResponse.read_from((b"", ENDPOINT))) is None
