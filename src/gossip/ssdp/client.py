import logging

from aiostream import Stream

from gossip.http.client import HTTPClient
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.network.endpoint import Endpoint
from gossip.ssdp.uri import SSDP_HOST

log = logging.getLogger(__name__)


class SSDPClient(HTTPClient):
    """Sends SSDP protocol requests and receives responses."""

    async def broadcast(self, message: HTTPRequest) -> None:
        """Sends out an SSDP message over the default broadcast channel."""
        await self.prompter.broadcast(message, SSDP_HOST)

    async def broadcast_request(self, message: HTTPRequest, max_wait: int = 5) -> Stream[HTTPResponse]:
        """Sends out an SSDP request over the default broadcast channel."""
        return await self.prompter.broadcast_prompt(message, SSDP_HOST, max_wait=max_wait)

    async def unicast_request(self, message: HTTPRequest, remote_host: Endpoint) -> HTTPResponse | None:
        """Sends out an SSDP message to the specified address & port."""
        return await self.prompter.prompt_udp(message, remote_host)
