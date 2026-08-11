import asyncio
import logging
from types import TracebackType

from gossip.internet.uri import URI
from gossip.ssdp.client import SSDPClient
from gossip.ssdp.extension import DISCOVER
from gossip.ssdp.server import SSDPServer
from gossip.ssdp.uri import SSDP_HOST
from gossip.upnp.resource import UPnPDevice

log = logging.getLogger(__name__)


class SSDPDevice:
    """A device that can be interacted with over SSDP."""

    upnp_device: UPnPDevice
    server: SSDPServer
    client: SSDPClient

    def __init__(self, upnp_device: UPnPDevice, path: str = "/device.xml") -> None:
        self.upnp_device = upnp_device
        self.server = SSDPServer({URI.parse(path): self.upnp_device}, (DISCOVER,))
        self.client = SSDPClient()

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
                "NT": path,
                "NTS": str(subtype),
                "Cache-Control": "max-age=1800",
                "Location": str(path),
                **subresource_headers,
            }
            for path, subresource_headers in self.upnp_device.items()
        )
        responses = (self.client.notify(notification) for notification in notifications)
        completions = await asyncio.gather(*responses)
        await asyncio.gather(*completions)

    async def __aenter__(self):
        server = await self.server.__aenter__()

        # Send our waking-up notifications, and wait for them to actually
        # land - we want to fail fast at startup if we can't reach the
        # network on every interface we're configured to use.
        await self.notify(URI.ssdp("alive"))
        return server

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None):
        # Send our powering-down notifications - a flaky interface shouldn't
        # crash us on the way out, so we'll just log it instead.
        try:
            await self.notify(URI.ssdp("byebye"))
        except Exception:
            log.warning("Failed to send byebye notification.", exc_info=True)
