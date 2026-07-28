import asyncio
import logging
from asyncio.streams import StreamReader, StreamWriter
from collections.abc import Buffer
from functools import cache
from typing import Awaitable, Callable, Iterable, Mapping, Self

from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable
from gossip.utils.multidict import multidict

CRLF = "\r\n"
BODY_DELIMITER = CRLF * 2
BODY_DELIMITER_BYTES = BODY_DELIMITER.encode()

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


async def read_into_memory(reader: StreamReader) -> Buffer:
    """A default body reader that reads the entire body into memory."""
    return await reader.read()


class InternetMessage(Serializable):
    """An ARPA Internet Text Message, in the format defined in RFC 822.

    It consists of a start line, a list of key: value headers separated by
    newlines, a request body in bytes format, and a list of key: value trailers
    separated by newlines again. It should be suitable for MIME emails, Usenet
    group discussions, or SSDP/HTTP request/responses.
    """

    start_line: Iterable[str]
    headers: multidict
    body: Buffer | None
    trailers: multidict

    def __init__(self, start_line: Iterable[str], headers: Mapping[str, str], body: Buffer | None = None, trailers: Mapping[str, str] | None = None):
        """Create a new InternetMessage from a start line, headers, an an optional body and trailers."""
        self.start_line = start_line
        self.headers = multidict(headers)
        self.body = body
        self.trailers = multidict(trailers or {})

    @cache
    def __repr__(self) -> str:
        return " ".join(map(str, tuple(self.start_line)))

    def __bytes__(self) -> bytes:
        output = bytearray()
        # Send a start line
        if self.start_line:
            start_line = " ".join(map(str, self.start_line)) + CRLF
            output.extend(start_line.encode())

        headers_dict = dict(self.headers)
        if self.body is not None and "Content-Length" not in headers_dict:
            headers_dict["Content-Length"] = str(len(self.body))

        header_items = (f"{key}: {value}" for key, value in headers_dict.items())
        headers_str = CRLF.join(tuple(header_items) + ("", ""))
        output.extend(headers_str.encode())

        if self.body is not None:
            output.extend(memoryview(self.body))

        return bytes(output)

    async def write_to(self, writer: StreamWriter):
        """Returns the message as a bytes object."""
        # Send a start line
        if self.start_line:
            start_line = " ".join(map(str, self.start_line)) + CRLF
            writer.write(start_line.encode())

        headers_dict = dict(self.headers)
        if self.body is not None and "Content-Length" not in headers_dict:
            headers_dict["Content-Length"] = str(len(self.body))

        # Trailing empty strings give us the double newline separating headers from body.
        header_items = (f"{key}: {value}" for key, value in headers_dict.items())
        headers_str = CRLF.join(tuple(header_items) + ("", ""))
        writer.write(headers_str.encode())
        await writer.drain()

        # Send the body & drain if needed.
        if self.body is not None:
            writer.write(memoryview(self.body))
            await writer.drain()

        # Send trailers, if we have any.
        if self.trailers:
            trailer_items = (f"{key}: {value}" for key, value in self.trailers.items())
            trailers_str = CRLF.join(tuple(trailer_items) + ("", ""))
            writer.write(trailers_str.encode())
            await writer.drain()

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint], body_reader: Callable[[StreamReader], Awaitable[Buffer]] = read_into_memory) -> Self | None:
        try:
            # Split the request into header and body
            if isinstance(reader, StreamReader):
                header_bytes = await reader.readuntil(BODY_DELIMITER_BYTES)
                header = header_bytes[: -len(BODY_DELIMITER_BYTES)].decode()
            else:
                header_bytes, _ = reader
                header = header_bytes.decode().rstrip(BODY_DELIMITER)

            log.debug("Read message head (%d bytes)", len(header_bytes))

            # The header is a sequence of lines separated by newlines, they're
            # short enough to be read into memory.
            lines = tuple(header.split(CRLF))
            if not lines or not lines[0]:
                return None
            start_line = lines[0].split(maxsplit=2)
            header_lines = filter(None, lines[1:])
            header_pairs = (line.split(":", maxsplit=1) for line in header_lines)

            # We'll read the headers into a dictionary
            headers = multidict({header_key: value.strip() for header_key, value in header_pairs})

            log.debug("Correctly decoded headers (%d pairs)", len(headers))

            # Read the body into a buffer of some kind, if we have one.
            if isinstance(reader, StreamReader):
                content_length_str = headers.get("Content-Length")
                if content_length_str is not None:
                    try:
                        content_length = int(content_length_str)
                        if content_length > 0:
                            body = await reader.readexactly(content_length)
                        else:
                            body = b""
                    except (ValueError, asyncio.IncompleteReadError):
                        body = b""
                elif body_reader is not read_into_memory:
                    body = await body_reader(reader)
                else:
                    body = b""
            else:
                body = b""

            log.debug("Done reading message body")
            return cls(start_line, headers, body)
        except (UnicodeDecodeError, ValueError) as e:
            log.exception(e)
            return None
