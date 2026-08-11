import logging
from asyncio import Future
from collections.abc import Mapping
from ipaddress import IPv4Address, IPv6Address, ip_address

from aiostream import Stream

from gossip.http.extension.client import ExtendedHTTPClient
from gossip.http.extension.constants import Strength
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPResponse
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.ssdp.extension import DISCOVER
from gossip.ssdp.headers import TCP_PORT
from gossip.ssdp.uri import SSDP_HOST, SSDP_PORT

log = logging.getLogger(__name__)


SSDP_URI = URI(scheme="ssdp", netloc=str(SSDP_HOST), path="*", params="", query="", fragment="")
SEARCH_EXTENSIONS: Mapping[Strength, Mapping[Extension, Mapping[str, str]]] = {
    Strength.MANDATORY: {DISCOVER: {}}
}


class SSDPClient(ExtendedHTTPClient):
    """A client to send SSDP protocol requests and receive responses."""

    async def notify(self, headers: Mapping[str, str] | None = None) -> Future:
        """Broadcasts out an SSDP `NOTIFY` message.

        Doesn't wait for the send to land - returns a future for its
        completion, so callers can decide whether to await it or not.
        """
        return await self.broadcast("NOTIFY", SSDP_URI, headers)

    async def broadcast_search(self, headers: dict[str, str] | None = None, max_wait: int = 5, tcp_port: int | None = None) -> Stream[HTTPResponse]:
        """Broadcasts an SSDP `M-SEARCH` request and waits for responses."""
        # Callers can request a TCP port for responses to be sent to, indicated
        # by a known header.
        if tcp_port is not None:
            if headers is None:
                headers = {}
            headers[str(TCP_PORT)] = str(tcp_port)
        return await self.broadcast_request("SEARCH", SSDP_URI, headers, SEARCH_EXTENSIONS, max_wait=max_wait)

    async def unicast_search(self, address: IPv4Address | IPv6Address | str, headers: Mapping[str, str] | None = None) -> HTTPResponse | None:
        """Sends out an SSDP message to the specified address on the SSDP port.

        Will resolve the address if it is a hostname.
        """
        if isinstance(address, str):
            address = ip_address(address)
        destination = Endpoint(address, SSDP_PORT)

        target = URI(scheme="ssdp", netloc=str(destination), path="*", params="", query="", fragment="")

        return await self.request_udp("SEARCH", target, headers, SEARCH_EXTENSIONS)
