import logging
from asyncio.streams import StreamReader, StreamWriter
from collections.abc import Buffer
from functools import cache
from http import HTTPStatus
from typing import Awaitable, Callable, Iterable, Mapping, Self

from gossip.internet.message import InternetMessage, read_into_memory
from gossip.internet.product import Product
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable
from gossip.utils.multidict import multidict

log = logging.getLogger(__name__)

HTTP_PROTOCOL: Product = Product("HTTP", str(1.1))


class HTTPMessage(Serializable):
    """A base HTTP message."""

    """The start line, which will be strung together with spaces when serialized."""
    start_line: tuple[str, ...]

    """Request or response metadata."""
    headers: multidict

    """A message body, or `None` if unnecessary/not included."""
    body: Buffer | None

    def __init__(self, start_line: Iterable[str], headers: Mapping[str, str] | None = None, body: Buffer | None = None):
        self.start_line = tuple(start_line)
        self.headers = multidict(headers or {})
        self.body = body


class HTTPRequest(HTTPMessage):
    """A request for a resource that matches the accept constraints."""

    """A static product version string, like HTTP/1.1."""
    protocol: Product

    """The request method."""
    method: str

    """The target URI to identify the resource in question.

    Defaults to `*` if not specified.
    """
    target: URI

    def __init__(self, method: str, target: URI = URI.parse("*"), headers: Mapping[str, str] | None = None, body: Buffer | None = None, protocol: Product = HTTP_PROTOCOL):
        self.protocol = protocol
        self.method = method
        self.target = target

        # Start line format is `<METHOD> <path> <protocol>` i.e. `GET *`
        # and the writer will fill in the protocol for us.
        start_line = tuple(map(str, (self.method.upper(), self.target)))
        super().__init__(start_line, headers, body)

    async def write_to(self, writer: StreamWriter):
        """Write this message to a `StreamWriter`."""
        start_line = tuple(self.start_line) + (self.protocol,)
        message = InternetMessage(
            map(str, start_line),
            self.headers,
            self.body,
        )
        await message.write_to(writer)

    def __bytes__(self) -> bytes:
        """Convert to `bytes` for serialization."""
        start_line = tuple(self.start_line) + (self.protocol,)
        message = InternetMessage(
            map(str, start_line),
            self.headers,
            self.body,
        )
        return bytes(message)

    @cache
    def __repr__(self) -> str:
        return " ".join(map(str, self.start_line + (self.protocol,)))

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint], body_reader: Callable[[StreamReader], Awaitable[Buffer]] = read_into_memory) -> Self | None:
        internet_message = await InternetMessage.read_from(reader, body_reader=body_reader)
        if internet_message is None:
            # Return None directly - if we can't even recover a message from the
            # stream, it's probably jibberish.
            return None

        try:
            verb, path_string, protocol_string = internet_message.start_line
        except ValueError:
            log.warning(f"Invalid HTTP start line: {internet_message.start_line}")
            return None

        path = URI.parse(path_string)
        protocol = Product.parse(protocol_string)
        if protocol.name == HTTP_PROTOCOL.name:
            return cls(verb, path, internet_message.headers, internet_message.body, protocol)
        else:
            log.warning(f"Invalid HTTP protocol `{protocol_string}`, not decoding.")
            return None


class HTTPResponse(HTTPMessage):
    """A response for a resource representation matching the request."""

    """A static product version string, like HTTP/1.1."""
    protocol: Product

    status: HTTPStatus

    def __init__(self, status: HTTPStatus, headers: Mapping[str, str] | None = None, body: Buffer | None = None, protocol: Product = HTTP_PROTOCOL):
        self.status = status
        self.protocol = protocol

        start_line = tuple(map(str, (self.status.value, self.status.phrase)))
        super().__init__(start_line, headers, body)

    async def write_to(self, writer: StreamWriter):
        """Write this message to a `StreamWriter`."""
        start_line = (self.protocol,) + tuple(self.start_line)
        message = InternetMessage(
            map(str, start_line),
            self.headers,
            self.body,
        )
        await message.write_to(writer)

    def __bytes__(self) -> bytes:
        """Convert to `bytes` for serialization."""
        start_line = (self.protocol,) + tuple(self.start_line)

        message = InternetMessage(
            map(str, start_line),
            self.headers,
            self.body,
        )
        return bytes(message)

    @cache
    def __repr__(self) -> str:
        return " ".join(map(str, (self.protocol,) + self.start_line))

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint], body_reader: Callable[[StreamReader], Awaitable[Buffer]] = read_into_memory) -> Self | None:
        internet_message = await InternetMessage.read_from(reader, body_reader=body_reader)
        if internet_message is None:
            # Return None directly - if we can't even recover a message from the
            # stream, it's probably jibberish.
            return None

        try:
            protocol_string, response_code, response_string = internet_message.start_line
        except ValueError:
            log.warning(f"Invalid HTTP start line: {internet_message.start_line}")
            return None
        protocol = Product.parse(protocol_string)

        # We can parse multiple versions of HTTP so we'll match against the name
        if protocol.name == HTTP_PROTOCOL.name:
            return cls(
                HTTPStatus(int(response_code), response_string),
                internet_message.headers,
                internet_message.body,
                protocol,
            )
        else:
            return None
