import logging
from collections.abc import Mapping
from ipaddress import ip_address

# from gossip.dns.client import resolve_ip
from gossip.dns.client import DNSClient
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

    """A DNS client to use to resolve domain names & find IP addresses."""
    dns: DNSClient

    def __init__(self, prompter: Prompter[HTTPResponse] | None = None, agent: ProductStack | None = None, dns: DNSClient | None = None, radio: Radio | None = None):
        # Default prompter deserializes `HTTPResponse`s.
        if prompter is None:
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
        self.prompter = prompter

        if dns is None:
            dns = DNSClient(radio=radio)
        self.dns = dns

        if agent is None:
            agent = ProductStack.gossip()
        self.agent = agent

    def default_headers(self):
        return {
            "User-Agent": str(self.agent),
        }

    async def prepare(self, method: str, uri: URI, headers: Mapping[str, str] | None = None) -> tuple[HTTPRequest, Endpoint]:
        if not headers:
            headers = {}
        headers = dict(headers) | {"Host": str(uri.netloc)} | self.default_headers()

        if uri.hostname is not None:
            try:
                address = ip_address(uri.hostname)
            except ValueError:
                address = await self.dns.resolve_ip(uri.hostname)
        else:
            address = ip_address("127.0.0.1")
        destination = Endpoint(address, uri.port or 80)
        request_uri = uri._replace(scheme="", netloc=None)

        return HTTPRequest(method, request_uri, headers), destination

    async def request(self, method: str, uri: URI, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        request, destination = await self.prepare(method, uri, headers)
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
