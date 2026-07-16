import logging
from ipaddress import ip_address
from typing import Mapping

from gossip.dns import resolve_ip
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.product import ProductStack
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio

log = logging.getLogger(__name__)


class HTTPClient:
    """A client for making requests over HTTP."""

    """The `Prompter` used to open HTTP connections, send messages &
    deserialize responses."""
    prompter: Prompter[HTTPResponse]

    """The `ProductStack` identifying this client's agent."""
    agent: ProductStack

    def __init__(self, prompter: Prompter[HTTPResponse] | None = None, agent: ProductStack | None = None, radio: Radio | None = None):
        # Default prompter deserializes `HTTPResponse`s.
        if prompter is None:
            self.prompter = Prompter(HTTPResponse.read_from, radio=radio)

        self.agent = agent or ProductStack.gossip()

    def default_headers(self):
        return {
            "User-Agent": str(self.agent),
        }

    def prepare(self, method: str, uri: URI, headers: Mapping[str, str] | None = None) -> tuple[HTTPRequest, Endpoint]:
        if not headers:
            headers = dict()
        headers = dict(headers) | {"Host": str(uri.netloc)} | self.default_headers()

        if uri.hostname is not None:
            try:
                address = ip_address(uri.hostname)
            except ValueError:
                ip_addresses = resolve_ip(uri.hostname)
                address = ip_addresses[0]
        else:
            address = ip_address("127.0.0.1")
        destination = Endpoint(address, uri.port or 80)
        request_uri = uri._replace(scheme="", netloc=None)

        return HTTPRequest(method, request_uri, headers), destination

    async def request(self, method: str, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        request, destination = self.prepare(method, uri, headers)
        return await self.prompter.prompt_tcp(request, destination)

    async def get(self, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request("GET", uri, headers)

    async def post(self, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request("POST", uri, headers)

    async def put(self, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request("PUT", uri, headers)

    async def patch(self, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request("PATCH", uri, headers)

    async def delete(self, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request("DELETE", uri, headers)

    async def head(self, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        return await self.request("HEAD", uri, headers)
