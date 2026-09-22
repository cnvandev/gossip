import asyncio
import functools
import logging
from collections.abc import Mapping
from types import TracebackType

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio
from gossip.ssdp.extension import DISCOVER
from gossip.ssdp.server import SSDPServer
from gossip.ssdp.uri import SSDP_HOST
from gossip.upnp.resource import UPnPDevice

log = logging.getLogger(__name__)


class SSDPDevice:
    """A device that can be interacted with over SSDP."""

    upnp_device: UPnPDevice
    path: str
    server: SSDPServer
    prompter: Prompter[HTTPResponse]

    def __init__(self, upnp_device: UPnPDevice, path: str = "/device.xml", radio: Radio | None = None) -> None:
        self.upnp_device = upnp_device
        self.path = path
        self.server = SSDPServer({URI.parse(path): self.upnp_device}, (DISCOVER,), radio=radio)
        self.prompter = Prompter(HTTPResponse.read_from, radio=radio)

    def notification_request(self, headers: Mapping[str, str], local: Endpoint) -> HTTPRequest:
        """Builds one interface's `NOTIFY` request, `Location` pointing at our device description via `local`'s own address."""
        notify_headers = dict(headers) | {
            "Location": str(URI(scheme="http", netloc=str(local), path=self.path, query="", params="", fragment="")),
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
                "NT": path,
                "NTS": str(subtype),
                "Cache-Control": "max-age=1800",
                **subresource_headers,
            }
            for path, subresource_headers in self.upnp_device.items()
        )
        # `broadcast()` sends on every interface before it ever returns, so
        # awaiting these is enough to know the notifications actually went
        # out. Its own returned future instead tracks a *reply* - `NOTIFY`
        # never gets one, so awaiting that too would hang forever.
        await asyncio.gather(*(
            self.prompter.broadcast(functools.partial(self.notification_request, notification), SSDP_HOST)
            for notification in notifications
        ))

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
        finally:
            # Always tear the server down too, even if the byebye notification
            # didn't go out - otherwise its sockets outlive this block.
            await self.server.__aexit__(exc_type, exc_val, exc_tb)
