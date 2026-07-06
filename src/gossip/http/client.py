import logging

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.product import ProductStack
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

    async def request(self, request: HTTPRequest, destination: Endpoint) -> HTTPResponse | None:
        """Send an HTTP request to the given destination and return the response."""
        return await self.prompter.prompt_tcp(request, destination)
