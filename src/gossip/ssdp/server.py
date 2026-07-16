import asyncio
import logging
from typing import Iterable, Mapping

from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.server import HTTPServer
from gossip.http.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.replier import Replier
from gossip.network.serializer import Serializable
from gossip.ssdp.headers import TCP_PORT
from gossip.ssdp.responder import SSDPResponder
from gossip.ssdp.uri import SSDP_HOST

log = logging.getLogger(__name__)


class SSDPServer(HTTPServer):
    """Listens for requests via the Simple Service Discovery Protocol (SSDP) on
    behalf of an underlying resource (typically a device or service).

    The main difference between it and a typical `HTTPServer` is that it listens
    for SSDP requests on a specific UDP port, and has the ability to send
    out-of-band search responses over TCP. It also defaults to instantiating
    an `ExtendedHTTPResponder`.
    """

    """A prompter to send out-of-band responses over TCP, if needed."""
    prompter: Prompter[HTTPResponse]

    def __init__(
        self,
        resources: Mapping[URI, ResourceCollection],
        extensions: Iterable[Extension],
        replier: Replier[HTTPRequest] | None = None,
        responder: SSDPResponder | None = None,
        udp_port: int = SSDP_HOST.port,
    ):
        if not replier:
            udp_ports = {
                # Listen for multicast messages on the SSDP port.
                SSDP_HOST: HTTPRequest.read_from,
                udp_port: HTTPRequest.read_from,
            }
            replier = Replier(callback=self.respond, udp=udp_ports)

        if not responder:
            # If we're given a UDP port, include it in the static headers.
            if udp_port != SSDP_HOST.port:
                static_headers = {str(TCP_PORT): str(udp_port)}
            else:
                static_headers = None

            # SSDP uses extensions to support additional features, so we use the
            # default HTTP accessor to handle requests (and don't pass it in).
            responder = SSDPResponder(
                resources,
                extensions,
                static_headers=static_headers,
            )

        super().__init__(resources, replier, responder)

    async def respond(self, request: HTTPRequest, endpoint: Endpoint) -> Iterable[Serializable]:
        responses = await self.responder.respond(request, endpoint)

        # If the response is for a request with a TCP port specified, we'll
        # respond out-of-band here.
        if port_constraint := request.headers.get(str(TCP_PORT), None):
            log.debug("Writing to TCP port %s", port_constraint)
            destination = Endpoint(endpoint.address, int(port_constraint[0]))
            coroutines = (self.prompter.prompt_tcp(response, destination) for response in responses)
            await asyncio.gather(*coroutines)
            return tuple()
        else:
            return responses
