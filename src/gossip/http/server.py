import logging
from collections import Counter
from ipaddress import IPv4Address, IPv6Address
from typing import Mapping

from gossip.http.accessor import HTTPAccessor
from gossip.http.message import HTTPRequest
from gossip.http.responder import HTTPResponder
from gossip.internet.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.network.replier import Replier

log = logging.getLogger(__name__)


class HTTPServer:
    """A server that responds to HTTP requests with HTTP responses.

    Delegates out to 2 components: a **replier** that listens for incoming
    connections when the context manager enters and calls a method on the
    deserialized request messages, and a **responder** that produces
    serializable response messages to write back.
    """

    """Manages incoming connections and writes reply messages."""
    replier: Replier[HTTPRequest]

    """Produces serializable response objects (or errors) for the resource."""
    responder: HTTPResponder

    """A quick summary to display when the server starts."""
    summary: Mapping[str | IPv4Address | IPv6Address, int]

    def __init__(self, resources: Mapping[URI, ResourceCollection], replier: Replier[HTTPRequest] | None = None, responder: HTTPResponder | None = None):
        if replier is None:
            tcp_ports = {80: HTTPRequest.read_from}
            replier = Replier(callback=self.responder.respond, tcp=tcp_ports)
        if responder is None:
            accessor = HTTPAccessor()
            responder = HTTPResponder(resources, accessor)
        self.resources = resources
        self.replier = replier
        self.responder = responder

        # For convenience, we'll display the summary when the server starts.
        domains = Counter(uri.netloc or "*" for uri in resources.keys())
        ip_addresses = Counter(self.replier.radio.addresses())
        self.summary = {**domains, **{str(ip): count for ip, count in ip_addresses.items()}}

    async def __aenter__(self):
        await self.replier.__aenter__()
        log.info("%s serving %d resource(s): %s", self.__class__.__name__, len(self.summary), self.summary)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.replier.__aexit__(exc_type, exc_val, exc_tb)
