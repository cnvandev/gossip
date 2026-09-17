from collections.abc import Mapping
from http import HTTPMethod
from typing import Self

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.uri import URI
from gossip.network.session import PromptSession


class HTTPSession:
    """An open session for HTTP request-response messages.

    `read_reply()` and async-iteration (`async for`/`anext()`) both
    delegate to the underlying `PromptSession`, so a reply already sent
    for - e.g. the one `HTTPClient.request()` sends before returning -
    can be read straight off the session itself.
    """

    session: PromptSession[HTTPResponse]
    host: str
    default_headers: dict[str, str]

    def __init__(self, session: PromptSession[HTTPResponse], host: str, default_headers: dict[str, str]):
        self.session = session
        self.host = host
        self.default_headers = default_headers

    async def request(self, method: str, path: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        """Send a prompt down the connection, returning the reply.

        Returns `None` if the session ended without a reply."""
        merged = {"Connection": "keep-alive", "Host": self.host} | dict(headers or {}) | self.default_headers
        await self.session.send(HTTPRequest(method, path, merged))
        return await self.read_reply()

    async def read_reply(self) -> HTTPResponse | None:
        """Read and deserialize the next reply, or `None` if the session
        has already ended."""
        return await self.session.read_reply()

    async def get(self, path: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request(HTTPMethod.GET, path, headers)

    async def post(self, path: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request(HTTPMethod.POST, path, headers)

    async def put(self, path: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request(HTTPMethod.PUT, path, headers)

    async def patch(self, path: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request(HTTPMethod.PATCH, path, headers)

    async def delete(self, path: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request(HTTPMethod.DELETE, path, headers)

    async def head(self, path: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request(HTTPMethod.HEAD, path, headers)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> HTTPResponse:
        return await self.session.__anext__()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        await self.wait_closed()

    def close(self) -> None:
        """Close the underlying connection. Safe to call more than once."""
        self.session.close()

    async def wait_closed(self) -> None:
        """Wait for `close()` to finish."""
        await self.session.wait_closed()
