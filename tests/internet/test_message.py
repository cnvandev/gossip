from asyncio import Future, StreamReader, get_running_loop, sleep
from asyncio import run as run_async
from ipaddress import IPv4Address

import pytest

from gossip.internet.message import InternetMessage
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader

from ..support.streams import FakeStreamWriter

ENDPOINT = Endpoint(IPv4Address("127.0.0.1"), 80)


class TestInternetMessageSerialization:
    """Serializing an `InternetMessage` to its RFC 822-style wire form -
    restricted to headers-only messages (e.g. a `HEAD` request, or anything
    meant to fit in a single UDP datagram with no body)."""

    def test_start_line_is_space_joined_with_a_trailing_crlf(self):
        """The start line's parts are joined with spaces and end the line
        with CRLF."""
        message = InternetMessage(("GET", "/foo", "HTTP/1.1"), {})
        assert bytes(message).startswith(b"GET /foo HTTP/1.1\r\n")

    def test_empty_start_line_is_omitted(self):
        """A falsy start line (e.g. `()`) contributes nothing - the message
        begins directly with headers."""
        message = InternetMessage((), {"Host": "example.com"})
        assert bytes(message) == b"Host: example.com\r\n\r\n"

    def test_headers_are_colon_separated_and_crlf_joined(self):
        """Each header renders as `Key: value`, and a blank line marks the
        end of the header block."""
        message = InternetMessage((), {"Host": "example.com", "Accept": "*/*"})
        assert bytes(message) == b"Host: example.com\r\nAccept: */*\r\n\r\n"


class TestInternetMessageBytesRejectsBodyOrTrailers:
    """`bytes()` only supports headers-only messages - a non-empty body or
    any trailers can't be fully represented that way, so it raises rather
    than silently producing an incomplete or misleading serialization."""

    def test_raises_for_a_body(self):
        """A message with a (non-empty) body can't be serialized via
        `bytes()`."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hello"))
        with pytest.raises(ValueError):
            _ = bytes(message)

    def test_raises_for_trailers(self):
        """A message with trailers can't be serialized via `bytes()`
        either, since trailers have nowhere to go in this form."""
        message = InternetMessage((), {}, trailers={"X-Checksum": "abc"})
        with pytest.raises(ValueError):
            _ = bytes(message)

    def test_raises_for_both(self):
        """A message with both still raises, not just for one or the
        other."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"), trailers={"X-Checksum": "abc"})
        with pytest.raises(ValueError):
            _ = bytes(message)

    def test_does_not_raise_for_headers_only(self):
        """A plain headers-only message is exactly what `bytes()` is for."""
        _ = bytes(InternetMessage((), {"Host": "example.com"}))

    def test_raises_for_a_future_valued_trailers_even_if_already_resolved(self):
        """A `Future`-valued `trailers` fails this check too, even one
        that's already resolved - `bytes()` has no way to synchronously
        await it, and treating an already-done one specially would make
        this raise or not depending purely on timing."""

        async def check() -> None:
            future = get_running_loop().create_future()
            future.set_result({})
            message = InternetMessage((), {}, trailers=future)
            with pytest.raises(ValueError):
                _ = bytes(message)

        run_async(check())


class TestInternetMessageWriteTo:
    """Streaming an `InternetMessage` to a writer, which - unlike
    `bytes()` - also sends any trailers."""

    def test_matches_bytes_for_a_headers_only_message(self):
        """For a headers-only message - the one case `bytes()` supports -
        `write_to()` writes exactly the same bytes."""
        message = InternetMessage(("GET", "/foo", "HTTP/1.1"), {"Host": "example.com"})
        writer = FakeStreamWriter()
        run_async(message.write_to(writer))
        assert bytes(writer.buffer) == bytes(message)

    def test_trailers_are_written_after_the_body(self):
        """Trailers are appended right after the body, rendered the same
        way headers are, ending in a blank line."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"), trailers={"X-Checksum": "abc"})
        writer = FakeStreamWriter()
        run_async(message.write_to(writer))
        assert bytes(writer.buffer) == b"\r\nhiX-Checksum: abc\r\n\r\n"

    def test_no_trailers_written_when_there_are_none(self):
        """With an empty trailers mapping, nothing is written beyond the
        body."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"))
        writer = FakeStreamWriter()
        run_async(message.write_to(writer))
        assert bytes(writer.buffer) == b"\r\nhi"

    def test_awaits_a_future_valued_trailers_before_writing_them(self):
        """Trailers that aren't known yet at construction time - e.g. a
        checksum computed while streaming the body above - can be a
        `Future` instead of a plain mapping. `write_to()` genuinely
        suspends waiting for it, after the body, rather than just
        happening to read whatever value is there by the time it gets
        there - it only serializes trailers once the future actually
        resolves."""

        async def write_it() -> bytes:
            future = get_running_loop().create_future()
            message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"), trailers=future)
            writer = FakeStreamWriter()

            write_task = get_running_loop().create_task(message.write_to(writer))
            # Let write_to() run as far as it can: start line, headers, and
            # body all complete without any real suspension (FakeStreamWriter's
            # drain() doesn't actually wait), so this is enough for it to
            # reach - and genuinely suspend on - the unresolved future.
            await sleep(0)
            assert not write_task.done()

            future.set_result({"X-Checksum": "abc"})
            await write_task
            return bytes(writer.buffer)

        assert run_async(write_it()) == b"\r\nhiX-Checksum: abc\r\n\r\n"

    def test_writes_nothing_extra_when_the_future_resolves_empty(self):
        """A `Future`-valued `trailers` that resolves to an empty mapping
        behaves the same as an empty plain mapping - nothing written
        beyond the body."""

        async def write_it() -> bytes:
            future = get_running_loop().create_future()
            future.set_result({})
            message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"), trailers=future)
            writer = FakeStreamWriter()
            await message.write_to(writer)
            return bytes(writer.buffer)

        assert run_async(write_it()) == b"\r\nhi"


class TestInternetMessageRepr:
    """`repr()` formatting - just the start line, space-joined."""

    def test_repr_is_the_space_joined_start_line(self):
        """The repr is the start line's parts joined with spaces, no
        headers or body."""
        message = InternetMessage(("GET", "/foo", "HTTP/1.1"), {"Host": "example.com"}, body=BufferedReader.for_bytes(b"hi"))
        assert repr(message) == "GET /foo HTTP/1.1"


class TestInternetMessageReadFromTuple:
    """Parsing an `InternetMessage` from a `(bytes, Endpoint)` pair - the
    whole message already sitting in memory, as opposed to a live stream."""

    def test_round_trips_a_headers_only_message(self):
        """A header-only message round-trips to no body at all."""
        original = InternetMessage(("GET", "/foo", "HTTP/1.1"), {"Host": "example.com"})
        parsed = run_async(InternetMessage.read_from((bytes(original), ENDPOINT)))
        assert parsed is not None
        assert parsed.start_line == ["GET", "/foo", "HTTP/1.1"]
        assert dict(parsed.headers) == {"Host": "example.com"}
        assert parsed.body is None

    def test_ignores_bytes_following_the_header_delimiter(self):
        """Whatever bytes happen to follow the header's blank-line
        delimiter in the buffer, they're never turned into a body - a
        message parsed from an in-memory buffer (a UDP datagram) is
        headers-only, by design (see `read_from()`)."""
        data = b"GET /foo HTTP/1.1\r\nHost: example.com\r\n\r\nleftover-bytes"
        parsed = run_async(InternetMessage.read_from((data, ENDPOINT)))
        assert parsed is not None
        assert parsed.body is None

    def test_returns_none_for_an_empty_buffer(self):
        """An empty buffer has no start line to parse, so it fails
        cleanly with `None`."""
        assert run_async(InternetMessage.read_from((b"", ENDPOINT))) is None

    def test_returns_none_for_a_header_line_without_a_colon(self):
        """A genuinely malformed header line (no `:` to split on) is caught
        and reported as `None`, rather than propagating the underlying
        `ValueError`."""
        data = b"GET /foo HTTP/1.1\r\nNotAHeaderLine\r\n\r\n"
        assert run_async(InternetMessage.read_from((data, ENDPOINT))) is None


class TestInternetMessageReadFromStream:
    """Parsing an `InternetMessage` from a live `asyncio.StreamReader` -
    only the header block is actually read; the body is left for the
    caller to pull off the same reader afterward."""

    def test_body_is_the_reader_itself(self):
        """`body` is the same `StreamReader` passed in, positioned right
        after the headers - regardless of whether Content-Length is
        present, or of what (if anything) actually follows."""
        reader = BufferedReader.for_bytes(b"GET /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 5\r\n\r\nhello")
        message = run_async(InternetMessage.read_from(reader))
        assert message is not None
        assert message.body is reader

    def test_caller_can_read_the_body_off_the_returned_reader(self):
        """Since `body` is the live reader, the caller can pull exactly
        the bytes they expect straight off it, using `Content-Length` from
        the parsed headers."""

        async def read_it() -> bytes:
            reader = BufferedReader.for_bytes(b"GET /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 5\r\n\r\nhello")
            message = await InternetMessage.read_from(reader)
            assert message is not None and message.body is not None
            content_length = int(message.headers["Content-Length"])
            return await message.body.readexactly(content_length)

        assert run_async(read_it()) == b"hello"

    def test_body_is_the_reader_even_with_nothing_declared_to_follow(self):
        """A message with no `Content-Length` still gets the reader as its
        `body` - `read_from()` makes no judgment about whether there's
        anything left to read; that's for the caller to decide."""
        reader = BufferedReader.for_bytes(b"GET /foo HTTP/1.1\r\nHost: example.com\r\n\r\n")
        parsed = run_async(InternetMessage.read_from(reader))
        assert parsed is not None
        assert isinstance(parsed.body, StreamReader)
