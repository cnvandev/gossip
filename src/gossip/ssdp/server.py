import asyncio
import functools
import logging
from collections.abc import Iterable, Mapping
from types import TracebackType

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.resource import ResourceCollection
from gossip.http.server import HTTPServer
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio
from gossip.network.replier import Replier
from gossip.ssdp.extension import DISCOVER
from gossip.ssdp.headers import SEARCH_PORT, TCP_PORT
from gossip.ssdp.responder import SSDPResponder
from gossip.ssdp.uri import SSDP_HOST

log = logging.getLogger(__name__)


class SSDPServer(HTTPServer):
    """A device that can be interacted with over SSDP.

    Serves `upnp_device`'s description over unicast HTTP and responds to
    `M-SEARCH`es like any `HTTPServer`, but also listens on the SSDP
    multicast address, can send out-of-band search responses over TCP, and
    announces itself with `NOTIFY` requests on entering/exiting as an async
    context manager.
    """

    """A prompter to send out-of-band responses over TCP, and `NOTIFY`
    announcements over multicast."""
    prompter: Prompter[HTTPResponse]

    def __init__(
        self,
        resources: Mapping[URI, ResourceCollection],
        prompter: Prompter[HTTPResponse] | None = None,
        replier: Replier[HTTPRequest] | None = None,
        responder: SSDPResponder | None = None,
        udp_port: int = SSDP_HOST.port,
        radio: Radio | None = None,
    ):
        if prompter is None:
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
        self.prompter = prompter

        if replier is None:
            udp_ports = {
                # Listen for multicast messages on the SSDP port.
                SSDP_HOST: HTTPRequest.read_from,
                udp_port: HTTPRequest.read_from,
            }
            tcp_ports = {
                udp_port: HTTPRequest.read_from,
            }
            replier = Replier(callback=self.respond, udp=udp_ports, tcp=tcp_ports, radio=radio)

        if responder is None:
            # If we're given a UDP port, include it in the static headers.
            if udp_port != SSDP_HOST.port:
                static_headers = {str(SEARCH_PORT): str(udp_port)}
            else:
                static_headers = None

            # SSDP uses extensions to support additional features, so we use the
            # default HTTP accessor to handle requests (and don't pass it in).
            responder = SSDPResponder(
                resources,
                (DISCOVER,),
                static_headers=static_headers,
            )

        super().__init__(resources, replier, responder)

    def notification_request(self, headers: Mapping[str, str], local: Endpoint) -> HTTPRequest:
        """Builds one interface's `NOTIFY` request, `Location` pointing at our device description via `local`'s own address."""
        base = URI.parse(f"http://{local}")
        notify_headers = dict(headers) | {
            "Location": str(base.join(headers["Location"])),
        }
        return HTTPRequest("NOTIFY", URI.parse("*"), notify_headers)

    async def notify(self, subtype: URI) -> None:
        """Sends notification requests for the resources we're serving.

        Await this to send every notification and wait for them all to land,
        raising if any of them fail. For a fire-and-forget send instead,
        schedule it as a task (e.g. `asyncio.create_task(...)`) rather than
        awaiting it directly.
        """
        notifications = (
            {
                "Host": str(SSDP_HOST),
                "NT": subresource_path,
                "NTS": str(subtype),
                "Location": str(uri),
                "Cache-Control": "max-age=1800",
                **subresource_headers,
            }
            for uri, resource in self.resources.items()
            for subresource_path, subresource_headers in resource.items()
        )
        # `broadcast()` sends on every interface before it ever returns, so
        # awaiting these is enough to know the notifications actually went
        # out. Its own returned future instead tracks a *reply* - `NOTIFY`
        # never gets one, so awaiting that too would hang forever.
        await asyncio.gather(*(
            self.prompter.broadcast(functools.partial(self.notification_request, notification), SSDP_HOST)
            for notification in notifications
        ))

    async def respond(self, request: HTTPRequest, remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        responses = await self.responder.respond(request, remote, local)

        # If the response is for a request with a TCP port specified, we'll
        # respond out-of-band here.
        if port_constraint := request.headers.get(str(TCP_PORT), None):
            log.debug("Writing to TCP port %s", port_constraint)
            destination = Endpoint(remote.address, int(port_constraint))
            sessions = await asyncio.gather(*(self.prompter.prompt_tcp(response, destination) for response in responses))
            await asyncio.gather(*(session.read_reply() for session in sessions))
            return ()
        else:
            return responses

    async def __aenter__(self):
        await super().__aenter__()

        # Send our waking-up notifications, and wait for them to actually
        # land - we want to fail fast at startup if we can't reach the
        # network on every interface we're configured to use.
        await self.notify(URI.ssdp("alive"))
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None):
        # Send our powering-down notifications - a flaky interface shouldn't
        # crash us on the way out, so we'll just log it instead.
        try:
            await self.notify(URI.ssdp("byebye"))
        except Exception:
            log.warning("Failed to send byebye notification.", exc_info=True)
        finally:
            # Always tear the server down too, even if the byebye notification
            # didn't go out - otherwise its sockets outlive this block.
            await super().__aexit__(exc_type, exc_val, exc_tb)
