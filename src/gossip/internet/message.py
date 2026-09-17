import logging
from asyncio.streams import StreamReader, StreamWriter
from collections.abc import Iterable, Mapping
from typing import Self, override

from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable
from gossip.utils.multidict import multidict

CRLF = "\r\n"
BODY_DELIMITER = CRLF * 2
BODY_DELIMITER_BYTES = BODY_DELIMITER.encode()

BODY_CHUNK_SIZE = 65536

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def parse_field_lines(lines: Iterable[str]) -> multidict:
    """Parse `name: value` field-lines into a multidict - the format an
    HTTP header block and a trailer section share alike, so both
    `read_from()` (headers) and `wait_trailers()` (trailers) parse
    through here rather than each keeping its own copy.
    """
    pairs = (line.split(":", maxsplit=1) for line in lines)
    return multidict({key: value.strip() for key, value in pairs})


class InternetMessage(Serializable):
    """An ARPA Internet Text Message, in the format defined in RFC 822.

    It consists of a start line, a list of key: value headers separated by
    newlines, a request body in bytes format, and a list of key: value trailers
    separated by newlines again. It should be suitable for MIME emails, Usenet
    group discussions, or SSDP/HTTP request/responses.
    """

    """The first line of the message, to be serialized by ' '.join()ing it.

    e.g. `["GET", "/", "HTTP/1.1"]`.
    e.g. `["HTTP/1.1", "200", "OK"]`.
    e.g. `["ARTICLE", "3000234"]`
    e.g. `["220", "3000234", "<article-id@example.com>"]`

    Empty in e.g. emails.
    """
    start_line: Iterable[str]

    """HTTP headers, deserialized as a key-value pair mapping."""
    headers: multidict

    """A message body whose buffer is ready to be read. Callers constructing a
    message from an in-memory buffer are responsible for setting it up
    themselves - the initializer takes a reader as-is. A message that has been
    serialized to a `bytes` buffer when received  (like a UDP datagram) and has
    `None` instead."""
    body: StreamReader | None

    """Trailer fields, deserialized as a key-value pair mapping - `None`
    until they're actually known. Given explicitly at construction, it's
    known immediately; left unset, it's `None` until `wait_trailers()`
    computes it.

    Built from whatever's left on `body` once the caller's done reading the
    message's real content off it.
    """
    trailers: multidict | None

    def __init__(self, start_line: Iterable[str], headers: Mapping[str, str], body: StreamReader | None = None, trailers: Mapping[str, str] | None = None):
        """Create a new InternetMessage from a start line, headers, an an optional body and trailers."""
        self.start_line = start_line
        self.headers = multidict(headers)
        self.body = body
        self.trailers = multidict(trailers) if trailers is not None else None

    def __repr__(self) -> str:
        return " ".join(map(str, tuple(self.start_line)))

    async def wait_trailers(self) -> multidict | None:
        """Returns `trailers`, computing it first if it isn't already
        known - `None` if there's no `body` to read from at all.
        Memoized into `trailers` in place, so repeated calls don't
        re-read `body`.

        Computing it means dumping whatever's left of `body` into memory
        and parsing it as trailer field-lines, whole - it's on the caller
        to have already read exactly the message's real content off
        `body` and stopped there before calling this.
        """
        if self.trailers is not None:
            return self.trailers
        if self.body is None:
            return None

        data = await self.body.read()
        lines = (line.strip() for line in data.decode().split(CRLF))
        self.trailers = parse_field_lines(filter(None, lines))
        return self.trailers

    @override
    def __bytes__(self) -> bytes:
        """Serializes a headers-only message - a `HEAD` request, or
        anything else meant to fit in a single UDP datagram with no body.

        A message with a body or trailers can't be fully represented this
        way; use `write_to()` instead, which streams the body and sends
        trailers too. A message whose `trailers` are still pending fails
        this check too - but that's already covered by `self.body is not
        None`, since `trailers` can only be pending when there's a body
        to wait on in the first place.
        """
        if self.body is not None or self.trailers:
            raise ValueError("bytes() only supports headers-only messages - use write_to() for a body or trailers.")

        # We'll serialize to a bytearray to build it incrementally.
        output = bytearray()

        # Send a start line
        if self.start_line:
            start_line = " ".join(map(str, self.start_line)) + CRLF
            output.extend(start_line.encode())

        header_items = (f"{key}: {value}" for key, value in self.headers.items())
        headers_str = CRLF.join(tuple(header_items) + ("", ""))
        output.extend(headers_str.encode())

        return bytes(output)

    @override
    async def write_to(self, writer: StreamWriter):
        """Returns the message as a bytes object."""
        # Send a start line
        if self.start_line:
            start_line = " ".join(map(str, self.start_line)) + CRLF
            writer.write(start_line.encode())

        # Trailing empty strings give us the double newline separating headers from body.
        header_items = (f"{key}: {value}" for key, value in self.headers.items())
        headers_str = CRLF.join(tuple(header_items) + ("", ""))
        writer.write(headers_str.encode())
        await writer.drain()

        # Stream the body asynchronously in chunks.
        if self.body is not None:
            while chunk := await self.body.read(BODY_CHUNK_SIZE):
                writer.write(chunk)
                await writer.drain()

        # Trailers might not be known yet - wait for them here, after the
        # body's been streamed out (and so, by construction, fully
        # drained) above.
        trailers = await self.wait_trailers()

        # Send trailers, if we have any.
        if trailers:
            trailer_items = (f"{key}: {value}" for key, value in trailers.items())
            trailers_str = CRLF.join(tuple(trailer_items) + ("", ""))
            writer.write(trailers_str.encode())
            await writer.drain()

    @override
    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None:
        try:
            # Split the request into header and body, either from the stream
            # or an in-memory buffer (i.e. reading from a UDP datagram.)
            if isinstance(reader, StreamReader):
                header_bytes = await reader.readuntil(BODY_DELIMITER_BYTES)
                header = header_bytes[: -len(BODY_DELIMITER_BYTES)].decode()
                body = reader
            else:
                full_bytes, _ = reader
                header_bytes, _, _ = full_bytes.partition(BODY_DELIMITER_BYTES)
                header = header_bytes.decode()

                # A message read from an in-memory buffer (a UDP datagram)
                # never has a body, as per the SSDP spec. We're deliberately
                # enforcing that here, I doubt there's a useful application
                # for one.
                body = None

            log.debug("Read message head (%d bytes)", len(header_bytes))

            # The header is a sequence of lines separated by newlines, they're
            # short enough to be read into memory.
            lines = tuple(h.strip() for h in header.split(CRLF))
            if not lines or not lines[0]:
                return None
            start_line = lines[0].split(maxsplit=2)
            headers = parse_field_lines(filter(None, lines[1:]))

            log.debug("Correctly decoded headers (%d pairs)", len(headers))

            # The body hasn't been read yet, we hand back the connection's
            # reader (or `None`), for consumers to read directly.
            return cls(start_line, headers, body)
        except (UnicodeDecodeError, ValueError) as e:
            log.error(e)
            return None
        except EOFError:
            # The peer closed the connection before sending anything (or
            # anything more) - not an error, just nothing left to read.
            # `IncompleteReadError` (raised by `readuntil()`) is an
            # `EOFError` subclass, so this also catches that.
            return None
