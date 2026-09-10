from asyncio import StreamReader
from asyncio import run as run_async
from http import HTTPStatus
from ipaddress import IPv4Address

import pytest

from gossip.http.message import HTTPMessage, HTTPRequest, HTTPResponse
from gossip.internet.message import InternetMessage
from gossip.internet.product import Product
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader

from ..support.streams import FakeStreamWriter

ENDPOINT = Endpoint(IPv4Address("127.0.0.1"), 80)


class TestHTTPMessageConstruction:
    """`HTTPMessage` builds a canonical `InternetMessage` (`self.message`)
    at construction time - everything else (`headers`, `trailers`,
    `wait_trailers()`) is a pass-through to it, so there's only ever one
    copy of any of that to keep in sync."""

    def test_message_is_an_internet_message(self):
        message = HTTPMessage(("start",))
        assert isinstance(message.message, InternetMessage)

    def test_headers_is_the_same_object_as_the_messages_headers(self):
        """Not just an equal copy - the literal same `multidict`, since
        `headers` is a property reading straight through to `self.message`."""
        message = HTTPMessage(("start",), {"Host": "example.com"})
        assert message.headers is message.message.headers

    def test_trailers_is_the_same_object_as_the_messages_trailers(self):
        message = HTTPMessage(("start",), trailers={"X-Checksum": "abc"})
        assert message.trailers is message.message.trailers

    def test_body_defaults_to_none(self):
        message = HTTPMessage(("start",))
        assert message.body is None

    def test_body_mirrors_what_was_given(self):
        """`body` is `HTTPMessage`'s own attribute, not a property - but
        for now (no framing layer applied yet) it's exactly the same
        object handed to the constructor, same as `self.message.body`."""
        body = BufferedReader.for_bytes(b"hi")
        message = HTTPMessage(("start",), body=body)
        assert message.body is body
        assert message.body is message.message.body


class TestHTTPMessageTrailers:
    """`HTTPMessage.trailers`/`wait_trailers()` - pure pass-throughs to
    `self.message`, so they follow exactly the same rules `InternetMessage`
    itself does."""

    def test_defaults_to_none_and_needs_no_running_event_loop(self):
        """Plain construction with no `trailers` given doesn't require an
        event loop at all - it's `None`, not something bound to a
        background task."""
        message = HTTPMessage(("start",))
        assert message.trailers is None

    def test_a_plain_mapping_is_stored_immediately(self):
        message = HTTPMessage(("start",), trailers={"X-Checksum": "abc"})
        assert dict(message.trailers) == {"X-Checksum": "abc"}

    def test_wait_trailers_returns_a_plain_mapping_without_reading_anything(self):
        async def check() -> dict[str, str] | None:
            message = HTTPMessage(("start",), trailers={"X-Checksum": "abc"})
            trailers = await message.wait_trailers()
            return dict(trailers) if trailers is not None else None

        assert run_async(check()) == {"X-Checksum": "abc"}

    def test_wait_trailers_drains_body_when_not_given_upfront(self):
        """With no explicit `trailers`, `wait_trailers()` falls through to
        `InternetMessage`'s own behavior: drain `body`, parse it as a
        trailer section."""

        async def check() -> dict[str, str] | None:
            body = BufferedReader.for_bytes(b"X-Checksum: abc\r\n\r\n")
            message = HTTPMessage(("start",), body=body)
            trailers = await message.wait_trailers()
            return dict(trailers) if trailers is not None else None

        assert run_async(check()) == {"X-Checksum": "abc"}


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
        only the wire form (the underlying message's start line) is
        upper-cased."""
        request = HTTPRequest("get", URI.parse("/foo"))
        assert request.method == "get"

    def test_wire_start_line_is_upper_cased_method_target_and_protocol(self):
        """The underlying message's start line is `(METHOD, target,
        protocol)`, method upper-cased - the full wire form, protocol
        included, unlike the old separate `start_line` attribute this
        replaces."""
        request = HTTPRequest("get", URI.parse("/foo"))
        assert request.message.start_line == ("GET", "/foo", "HTTP/1.1")

    def test_default_protocol_is_http_1_1(self):
        """Omitting a protocol defaults to HTTP/1.1."""
        assert HTTPRequest("GET", URI.parse("/foo")).protocol == Product("HTTP", "1.1")


class TestHTTPRequestSerialization:
    """Serializing an `HTTPRequest` to wire bytes: `METHOD target PROTOCOL`
    followed by headers and an optional body."""

    def test_bytes_appends_the_protocol_to_the_start_line(self):
        """The serialized wire form has the protocol as a third token."""
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
        """`repr()` shows the same content as the start of the wire form -
        it's a pass-through to the underlying message's own `repr()`."""
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

    def test_chunked_body_is_decoded(self):
        """A `Transfer-Encoding: chunked` body is unwrapped by the time
        it reaches `body` - the caller reads decoded content directly,
        not raw chunk framing."""

        async def read_it() -> bytes:
            reader = StreamReader()
            reader.feed_data(b"POST /foo HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n")
            reader.feed_eof()
            request = await HTTPRequest.read_from(reader)
            assert request is not None
            assert request.body is not None
            return await request.body.read()

        assert run_async(read_it()) == b"hello"

    def test_invalid_transfer_encoding_is_rejected(self):
        """A message naming a coding this can't decode is refused
        outright, rather than passed through undecoded. Needs a real
        stream (not the tuple form, which never carries a body at all,
        so there'd be nothing to reject)."""

        async def read_it() -> HTTPRequest | None:
            reader = StreamReader()
            reader.feed_data(b"POST /foo HTTP/1.1\r\nTransfer-Encoding: compress\r\n\r\ngarbage")
            reader.feed_eof()
            return await HTTPRequest.read_from(reader)

        assert run_async(read_it()) is None

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

    def test_wire_start_line_is_protocol_code_and_phrase(self):
        """The underlying message's start line is `(protocol, code,
        phrase)`, the full wire form - unlike the old separate
        `start_line` attribute this replaces, which omitted protocol."""
        response = HTTPResponse(HTTPStatus.NOT_FOUND)
        assert response.message.start_line == ("HTTP/1.1", "404", "Not Found")

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
        """`repr()` shows the same content as the start of the wire form -
        it's a pass-through to the underlying message's own `repr()`."""
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

    def test_chunked_body_is_decoded(self):
        """A `Transfer-Encoding: chunked` body is unwrapped by the time
        it reaches `body` - the caller reads decoded content directly,
        not raw chunk framing."""

        async def read_it() -> bytes:
            reader = StreamReader()
            reader.feed_data(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n")
            reader.feed_eof()
            response = await HTTPResponse.read_from(reader)
            assert response is not None
            assert response.body is not None
            return await response.body.read()

        assert run_async(read_it()) == b"hello"

    def test_invalid_transfer_encoding_is_rejected(self):
        """A message naming a coding this can't decode is refused
        outright, rather than passed through undecoded. Needs a real
        stream (not the tuple form, which never carries a body at all,
        so there'd be nothing to reject)."""

        async def read_it() -> HTTPResponse | None:
            reader = StreamReader()
            reader.feed_data(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: compress\r\n\r\ngarbage")
            reader.feed_eof()
            return await HTTPResponse.read_from(reader)

        assert run_async(read_it()) is None
