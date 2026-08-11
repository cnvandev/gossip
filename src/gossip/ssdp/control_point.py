import logging
import uuid
from collections.abc import Iterable, Mapping
from uuid import UUID

from aiostream import Stream

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.product import ProductStack
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.radio import Radio
from gossip.network.replier import Replier
from gossip.ssdp.client import SSDPClient
from gossip.ssdp.headers import CPFN, CPUUID, TCP_PORT
from gossip.ssdp.uri import SSDP_HOST, SSDPTarget

log = logging.getLogger(__name__)


class SSDPControlPoint:
    """Something that sends control commands to other devices via SSDP."""

    friendly_name: str
    uuid: UUID

    replier: Replier[HTTPRequest]
    client: SSDPClient

    devices: dict[URI, Mapping[str, str]]

    def __init__(self, friendly_name: str, device_uuid: UUID | None = None, radio: Radio | None = None, agent: ProductStack | None = None):
        self.friendly_name = friendly_name
        if device_uuid is None:
            device_uuid = UUID(int=uuid.getnode())
        self.uuid = device_uuid
        self.devices = dict()

        self.client = SSDPClient(agent=agent, radio=radio)
        self.replier = Replier(callback=self.respond, udp={SSDP_HOST: HTTPRequest.read_from}, radio=radio)

    async def __aenter__(self):
        await self.replier.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.replier.__aexit__(exc_type, exc_val, exc_tb)

    async def respond(self, request: HTTPRequest, remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Handle an incoming message from the SSDP multicast address.

        Control points don't reply to `NOTIFY` messages, so this never
        returns any responses - it's only here to feed `self.devices`.
        """
        if request.method == "NOTIFY":
            await self.notify(request, remote)
        else:
            log.debug("Ignoring request `%s` from %s", request, remote)
        return ()

    async def notify(self, request: HTTPRequest, sender: Endpoint) -> None:
        """Handle a new update notification."""
        metadata = request.headers
        usn = URI.parse(metadata.get("USN", ""))
        log.info("%r on %s: %s", request, sender, usn)
        self.devices[usn] = metadata

    async def broadcast_search(self, target: SSDPTarget, max_wait: int = 5) -> Stream[HTTPResponse]:
        """Sends out an SSDP search message to the specified address."""
        log.info("Starting search for %s (for %ds).", target, max_wait)
        headers = {
            "Host": str(SSDP_HOST),
            str(CPUUID): str(self.uuid),
            str(CPFN): str(self.friendly_name),
            "ST": str(target),
            "MX": str(max_wait),
        }
        return await self.client.broadcast_search(headers, max_wait=max_wait)

    async def unicast_search(self, remote_host: Endpoint, target: SSDPTarget, tcp_port: int | None = None) -> HTTPResponse | None:
        """Sends out an SSDP search message to the specified address & port."""
        headers = {
            "Host": str(remote_host),
            str(CPUUID): str(self.uuid),
            str(CPFN): str(self.friendly_name),
            "ST": str(target),
        }

        # Let the host know if we're listening for responses via TCP.
        if tcp_port is not None:
            headers |= {
                str(TCP_PORT): str(tcp_port),
            }
            remote_host = Endpoint(remote_host.address, tcp_port)

        return await self.client.unicast_search(headers, remote_host)
