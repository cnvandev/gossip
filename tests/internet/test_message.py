from asyncio import StreamReader, get_running_loop, sleep
from asyncio import run as run_async
from ipaddress import IPv4Address

import pytest

from gossip.internet.message import InternetMessage
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import BufferedReader
from gossip.utils.multidict import multidict

from ..support.streams import FakeStreamWriter

ENDPOINT = Endpoint(IPv4Address("127.0.0.1"), 80)


class TestInternetMessageSerialization:
    """Serializing an `InternetMessage` to its RFC 822-style wire form -
    restricted to headers-only messages (e.g. a `HEAD` request, or anything
    meant to fit in a single UDP datagram with no body)."""

    def test_start_line_is_space_joined_with_a_trailing_crlf(self):
        """The start line's parts are joined with spaces, then CRLF."""
        message = InternetMessage(("GET", "/foo", "HTTP/1.1"), {})
        assert bytes(message) == b"GET /foo HTTP/1.1\r\n\r\n"

    def test_empty_start_line_is_omitted(self):
        """A falsy start line (e.g. `()`) contributes nothing."""
        message = InternetMessage((), {"Host": "example.com"})
        assert bytes(message) == b"Host: example.com\r\n\r\n"

    def test_headers_are_colon_separated_and_crlf_joined(self):
        """Each header renders as `Key: value`, ending in a blank line."""
        message = InternetMessage((), {"Host": "example.com", "Accept": "*/*"})
        assert bytes(message) == b"Host: example.com\r\nAccept: */*\r\n\r\n"


class TestInternetMessageBytesRejectsBodyOrTrailers:
    """`bytes()` only supports headers-only messages - a non-empty body or
    any trailers can't be fully represented that way, so it raises."""

    def test_raises_for_a_body(self):
        """A non-empty body can't be serialized via `bytes()`."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hello"))
        with pytest.raises(ValueError):
            _ = bytes(message)

    def test_raises_for_trailers(self):
        """Trailers can't be serialized via `bytes()` either."""
        message = InternetMessage((), {}, trailers={"X-Checksum": "abc"})
        with pytest.raises(ValueError):
            _ = bytes(message)

    def test_raises_for_both(self):
        """A message with both still raises."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"), trailers={"X-Checksum": "abc"})
        with pytest.raises(ValueError):
            _ = bytes(message)

    def test_does_not_raise_for_headers_only(self):
        """A plain headers-only message serializes fine."""
        _ = bytes(InternetMessage((), {"Host": "example.com"}))


class TestInternetMessageTrailers:
    """`InternetMessage.trailers` - `None` until known, populated in
    place; `wait_trailers()` computes it (by draining and parsing `body`)
    at most once."""

    def test_defaults_to_none_and_needs_no_running_event_loop(self):
        """Defaults to `None`, without needing a running event loop."""
        message = InternetMessage((), {})
        assert message.trailers is None

    def test_defaults_to_none_even_with_a_body(self):
        """A `body` alone doesn't populate `trailers`."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"))
        assert message.trailers is None

    def test_a_plain_mapping_is_stored_immediately(self):
        """An explicit `trailers` mapping is stored right away."""
        message = InternetMessage((), {}, trailers={"X-Checksum": "abc"})
        assert message.trailers is not None
        assert message.trailers.to_dict() == {"X-Checksum": "abc"}

    def test_wait_trailers_returns_none_when_there_is_no_body(self):
        """With no `body` at all, returns `None`."""

        async def check() -> multidict | None:
            message = InternetMessage((), {})
            return await message.wait_trailers()

        assert run_async(check()) is None

    def test_wait_trailers_drains_body_and_parses_it_as_trailers(self):
        """Drains `body` and parses it as a trailer section."""

        async def check() -> dict[str, str] | None:
            body = BufferedReader.for_bytes(b"X-Checksum: abc\r\n\r\n")
            message = InternetMessage((), {}, body=body)
            trailers = await message.wait_trailers()
            return dict(trailers) if trailers is not None else None

        assert run_async(check()) == {"X-Checksum": "abc"}

    def test_wait_trailers_parses_multiple_field_lines(self):
        """Multiple field-lines all parse into the result."""

        async def check() -> dict[str, str] | None:
            body = BufferedReader.for_bytes(b"A: 1\r\nB: 2\r\n\r\n")
            message = InternetMessage((), {}, body=body)
            trailers = await message.wait_trailers()
            return dict(trailers) if trailers is not None else None

        assert run_async(check()) == {"A": "1", "B": "2"}

    def test_wait_trailers_returns_empty_for_just_the_closing_crlf(self):
        """A bare closing CRLF is a valid, empty trailer section."""

        async def check() -> dict[str, str] | None:
            body = BufferedReader.for_bytes(b"\r\n")
            message = InternetMessage((), {}, body=body)
            trailers = await message.wait_trailers()
            return dict(trailers) if trailers is not None else None

        assert run_async(check()) == {}

    def test_wait_trailers_raises_for_a_field_line_without_a_colon(self):
        """A malformed field-line (no `:`) raises."""

        async def check() -> None:
            body = BufferedReader.for_bytes(b"NotAFieldLine\r\n\r\n")
            message = InternetMessage((), {}, body=body)
            await message.wait_trailers()

        with pytest.raises(ValueError):
            run_async(check())

    def test_wait_trailers_populates_trailers_in_place(self):
        """After awaiting, `trailers` itself holds the parsed result."""

        async def check() -> dict[str, str] | None:
            body = BufferedReader.for_bytes(b"X-Checksum: abc\r\n\r\n")
            message = InternetMessage((), {}, body=body)
            await message.wait_trailers()
            return dict(message.trailers) if message.trailers is not None else None

        assert run_async(check()) == {"X-Checksum": "abc"}

    def test_wait_trailers_reads_body_at_most_once(self):
        """A second call returns the same memoized value, without
        re-reading `body`."""

        async def check() -> dict[str, str] | None:
            body = BufferedReader.for_bytes(b"X-Checksum: abc\r\n\r\n")
            message = InternetMessage((), {}, body=body)
            first = await message.wait_trailers()
            second = await message.wait_trailers()
            assert first is second
            return dict(second) if second is not None else None

        assert run_async(check()) == {"X-Checksum": "abc"}

    def test_wait_trailers_returns_a_plain_mapping_without_reading_anything(self):
        """Given trailers upfront, returns them without reading `body`."""

        async def check() -> dict[str, str] | None:
            message = InternetMessage((), {}, trailers={"X-Checksum": "abc"})
            trailers = await message.wait_trailers()
            return dict(trailers) if trailers is not None else None

        assert run_async(check()) == {"X-Checksum": "abc"}

    def test_wait_trailers_waits_for_body_to_actually_have_data(self):
        """Genuinely suspends until `body` actually has data, rather than
        returning early."""

        async def check() -> dict[str, str] | None:
            body = StreamReader()
            message = InternetMessage((), {}, body=body)

            wait_task = get_running_loop().create_task(message.wait_trailers())
            await sleep(0)
            assert not wait_task.done()

            body.feed_data(b"X-Checksum: abc\r\n\r\n")
            body.feed_eof()
            trailers = await wait_task
            return dict(trailers) if trailers is not None else None

        assert run_async(check()) == {"X-Checksum": "abc"}


class TestInternetMessageWriteTo:
    """Streaming an `InternetMessage` to a writer, which - unlike
    `bytes()` - also sends any trailers."""

    def test_matches_bytes_for_a_headers_only_message(self):
        """For a headers-only message, writes the same bytes `bytes()` would."""
        message = InternetMessage(("GET", "/foo", "HTTP/1.1"), {"Host": "example.com"})
        writer = FakeStreamWriter()
        run_async(message.write_to(writer))
        assert bytes(writer.buffer) == bytes(message)

    def test_trailers_are_written_after_the_body(self):
        """Trailers are appended right after the body."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"), trailers={"X-Checksum": "abc"})
        writer = FakeStreamWriter()
        run_async(message.write_to(writer))
        assert bytes(writer.buffer) == b"\r\nhiX-Checksum: abc\r\n\r\n"

    def test_no_trailers_written_when_there_are_none(self):
        """With an empty trailers mapping, nothing is written beyond the body."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"), trailers={})
        writer = FakeStreamWriter()
        run_async(message.write_to(writer))
        assert bytes(writer.buffer) == b"\r\nhi"

    def test_no_trailers_given_resolves_to_nothing_extra_once_body_is_drained(self):
        """With no trailers given, nothing extra is written once the body
        is drained."""
        message = InternetMessage((), {}, body=BufferedReader.for_bytes(b"hi"))
        writer = FakeStreamWriter()
        run_async(message.write_to(writer))
        assert bytes(writer.buffer) == b"\r\nhi"


class TestInternetMessageRepr:
    """`repr()` formatting - just the start line, space-joined."""

    def test_repr_is_the_space_joined_start_line(self):
        """The repr is just the start line, no headers or body."""
        message = InternetMessage(("GET", "/foo", "HTTP/1.1"), {"Host": "example.com"}, body=BufferedReader.for_bytes(b"hi"))
        assert repr(message) == "GET /foo HTTP/1.1"


class TestInternetMessageReadFromTuple:
    """Parsing an `InternetMessage` from a `(bytes, Endpoint)` pair - the
    whole message already sitting in memory, as opposed to a live stream."""

    def test_round_trips_a_headers_only_message(self):
        """A headers-only message round-trips to no body at all."""
        original = InternetMessage(("GET", "/foo", "HTTP/1.1"), {"Host": "example.com"})
        parsed = run_async(InternetMessage.read_from((bytes(original), ENDPOINT)))
        assert parsed is not None
        assert parsed.start_line == ["GET", "/foo", "HTTP/1.1"]
        assert dict(parsed.headers) == {"Host": "example.com"}
        assert parsed.body is None

    def test_ignores_bytes_following_the_header_delimiter(self):
        """Bytes following the header delimiter never become a body."""
        data = b"GET /foo HTTP/1.1\r\nHost: example.com\r\n\r\nleftover-bytes"
        parsed = run_async(InternetMessage.read_from((data, ENDPOINT)))
        assert parsed is not None
        assert parsed.body is None

    def test_returns_none_for_an_empty_buffer(self):
        """An empty buffer fails cleanly with `None`."""
        assert run_async(InternetMessage.read_from((b"", ENDPOINT))) is None

    def test_returns_none_for_a_header_line_without_a_colon(self):
        """A malformed header line (no `:`) returns `None`."""
        data = b"GET /foo HTTP/1.1\r\nNotAHeaderLine\r\n\r\n"
        assert run_async(InternetMessage.read_from((data, ENDPOINT))) is None


class TestInternetMessageReadFromStream:
    """Parsing an `InternetMessage` from a live `asyncio.StreamReader` -
    only the header block is actually read; the body is left for the
    caller to pull off the same reader afterward."""

    def test_body_is_the_reader_itself(self):
        """`body` is the same `StreamReader`, positioned after the headers."""
        reader = BufferedReader.for_bytes(b"GET /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 5\r\n\r\nhello")
        message = run_async(InternetMessage.read_from(reader))
        assert message is not None
        assert message.body is reader

    def test_caller_can_read_the_body_off_the_returned_reader(self):
        """The caller can pull the body straight off the returned reader."""

        async def read_it() -> bytes:
            reader = BufferedReader.for_bytes(b"GET /foo HTTP/1.1\r\nHost: example.com\r\nContent-Length: 5\r\n\r\nhello")
            message = await InternetMessage.read_from(reader)
            assert message is not None and message.body is not None
            content_length = int(message.headers["Content-Length"])
            return await message.body.readexactly(content_length)

        assert run_async(read_it()) == b"hello"

    def test_body_is_the_reader_even_with_nothing_declared_to_follow(self):
        """Still gets the reader as `body`, even with no `Content-Length`."""
        reader = BufferedReader.for_bytes(b"GET /foo HTTP/1.1\r\nHost: example.com\r\n\r\n")
        parsed = run_async(InternetMessage.read_from(reader))
        assert parsed is not None
        assert isinstance(parsed.body, StreamReader)
