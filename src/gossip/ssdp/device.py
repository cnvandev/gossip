import asyncio
from types import TracebackType

from gossip.internet.uri import URI
from gossip.ssdp.client import SSDPClient
from gossip.ssdp.extension import DISCOVER
from gossip.ssdp.server import SSDPServer
from gossip.ssdp.uri import SSDP_HOST
from gossip.upnp.resource import UPnPDevice


class SSDPDevice:
    """A device that can be interacted with over SSDP."""

    upnp_device: UPnPDevice
    server: SSDPServer
    client: SSDPClient

    def __init__(self, upnp_device: UPnPDevice, path: str = "/device") -> None:
        self.upnp_device = upnp_device
        self.server = SSDPServer({URI.parse(path): self.upnp_device}, (DISCOVER,))
        self.client = SSDPClient()

    async def notify(self, subtype: URI) -> None:
        """Sends notification requests for the resources we're serving."""
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
        await asyncio.gather(*responses)

    async def __aenter__(self):
        server = await self.server.__aenter__()

        # Send our waking-up notifications.
        await self.notify(URI.ssdp("alive"))
        return server

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None):
        # Send our powering-down notifications.
        await self.notify(URI.ssdp("byebye"))
