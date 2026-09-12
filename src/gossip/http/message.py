import logging
from abc import ABC, abstractmethod
from asyncio.streams import StreamReader, StreamWriter
from collections.abc import Iterable, Mapping
from http import HTTPStatus
from typing import Self, override

from gossip.http.field import parse_field_values
from gossip.http.transfer import choose_encoding
from gossip.internet.message import InternetMessage
from gossip.internet.product import Product
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable
from gossip.utils.multidict import multidict

log = logging.getLogger(__name__)

HTTP_PROTOCOL: Product = Product("HTTP", str(1.1))


class HTTPMessage(ABC):
    """An HTTP message including a start line, headers, and optional body & trailers.

    This wraps a canonical `InternetMessage` (available via`self.message`),
    providing a `body` field that mirrors `self.message.body`, and
    `headers`/`trailers` that delegate to it. `body` is used exactly as
    given here - the constructor applies no framing of its own. For a
    message parsed via `read_from()`, `body` has already been decoded
    according to `Transfer-Encoding` (see `choose_encoding()`) before it
    ever reaches the constructor.

    Abstract - only ever meant to be built as a `HTTPRequest` or
    `HTTPResponse`, each of which assembles its own `start_line` before
    delegating here via `super().__init__()`.
    """

    """The underlying message this was built from."""
    message: InternetMessage

    """A readable message body, or `None` if none was included."""
    body: StreamReader | None

    @abstractmethod
    def __init__(self, start_line: Iterable[str], headers: Mapping[str, str] | None = None, body: StreamReader | None = None, trailers: Mapping[str, str] | None = None):
        self.message = InternetMessage(tuple(start_line), headers or {}, body, trailers)
        self.body = body

    @property
    def headers(self) -> multidict:
        return self.message.headers

    @property
    def trailers(self) -> multidict | None:
        return self.message.trailers

    async def wait_trailers(self) -> multidict | None:
        return await self.message.wait_trailers()

    @override
    def __repr__(self) -> str:
        return repr(self.message)

    def __bytes__(self) -> bytes:
        """Convert to `bytes` for serialization. Only supports headers-only
        messages (e.g. a `HEAD` request) - one with a body must be sent via
        `write_to()` instead."""
        return bytes(self.message)

    async def write_to(self, writer: StreamWriter) -> None:
        """Stream this message to a writer, body (and any trailers) included."""
        await self.message.write_to(writer)


class HTTPRequest(HTTPMessage, Serializable):
    """A request for a resource that matches the accept constraints."""

    """A static product version string, like HTTP/1.1."""
    protocol: Product

    """The request method."""
    method: str

    """The target URI to identify the resource in question.

    Defaults to `*` if not specified.
    """
    target: URI

    def __init__(self, method: str, target: URI, headers: Mapping[str, str] | None = None, body: StreamReader | None = None, protocol: Product = HTTP_PROTOCOL, trailers: Mapping[str, str] | None = None):
        self.protocol = protocol
        self.method = method
        self.target = target

        # Start line format is `<METHOD> <path> <protocol>`, e.g. `GET / HTTP/1.1`.
        start_line = tuple(map(str, (self.method.upper(), self.target, self.protocol)))
        super().__init__(start_line, headers, body, trailers)

    @override
    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None:
        internet_message = await InternetMessage.read_from(reader)
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
        if protocol.name != HTTP_PROTOCOL.name:
            log.warning(f"Invalid HTTP protocol `{protocol_string}`, not decoding.")
            return None

        codings = []
        if "transfer-encoding" in internet_message.headers:
            codings = [value.lower() for value, _ in parse_field_values(internet_message.headers["transfer-encoding"])]

        try:
            body = choose_encoding(codings, internet_message.body)
        except ValueError as e:
            log.warning(f"Invalid Transfer-Encoding: {e}")
            return None

        return cls(verb, path, internet_message.headers, body, protocol)


class HTTPResponse(HTTPMessage, Serializable):
    """A response for a resource representation matching the request."""

    """A static product version string, like HTTP/1.1."""
    protocol: Product

    """The HTTP status code and reason phrase for this response."""
    status: HTTPStatus

    def __init__(self, status: HTTPStatus, headers: Mapping[str, str] | None = None, body: StreamReader | None = None, protocol: Product = HTTP_PROTOCOL, trailers: Mapping[str, str] | None = None):
        self.status = status
        self.protocol = protocol

        # Start line format is `PROTOCOL code phrase`, e.g. `HTTP/1.1 200 OK`.
        start_line = tuple(map(str, (self.protocol, self.status.value, self.status.phrase)))
        super().__init__(start_line, headers, body, trailers)

    @override
    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None:
        internet_message = await InternetMessage.read_from(reader)
        if internet_message is None:
            # Return None directly - if we can't even recover a message from the
            # stream, it's probably jibberish.
            return None

        try:
            protocol_string, response_code, _response_string = internet_message.start_line
        except ValueError:
            log.warning(f"Invalid HTTP start line: {internet_message.start_line}")
            return None
        protocol = Product.parse(protocol_string)

        # We can parse multiple versions of HTTP so we'll match against the name
        if protocol.name != HTTP_PROTOCOL.name:
            return None

        codings = []
        if "transfer-encoding" in internet_message.headers:
            codings = [value.lower() for value, _ in parse_field_values(internet_message.headers["transfer-encoding"])]

        try:
            body = choose_encoding(codings, internet_message.body)
        except ValueError as e:
            log.warning(f"Invalid Transfer-Encoding: {e}")
            return None

        return cls(
            HTTPStatus(int(response_code)),
            internet_message.headers,
            body,
            protocol,
        )
