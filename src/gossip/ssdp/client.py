import logging
from typing import Mapping

from aiostream import Stream

from gossip.http.extension.client import ExtendedHTTPClient
from gossip.http.extension.constants import Strength
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPResponse
from gossip.internet.uri import URI
from gossip.ssdp.extension import DISCOVER
from gossip.ssdp.uri import SSDP_HOST

log = logging.getLogger(__name__)


SSDP_URI = URI(scheme="ssdp", netloc=str(SSDP_HOST), path="*", params="", query="", fragment="")
SEARCH_EXTENSIONS: Mapping[Strength, Mapping[Extension, Mapping[str, str]]] = {
    Strength.MANDATORY: {DISCOVER: {}}
}


class SSDPClient(ExtendedHTTPClient):
    """Sends SSDP protocol requests and receives responses."""

    async def notify(self, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        """Sends out an SSDP message over the default broadcast channel."""
        await self.broadcast("NOTIFY", SSDP_URI, headers)

    async def broadcast_search(self, headers: Mapping[str, str] | None = None, max_wait: int = 5) -> Stream[HTTPResponse]:
        """Sends out an SSDP request over the default broadcast channel."""
        return await self.broadcast_request("SEARCH", SSDP_URI, headers, SEARCH_EXTENSIONS, max_wait=max_wait)

    async def unicast_search(self, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        """Sends out an SSDP message to the specified address & port."""
        return await self.request_udp("SEARCH", SSDP_URI, headers, SEARCH_EXTENSIONS)
