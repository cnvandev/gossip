import asyncio
import logging
import sys
import uuid
from uuid import UUID

from gossip.internet.uri import URI
from gossip.ssdp.device import SSDPDevice
from gossip.ssdp.uri import MULTISCREEN_DOMAIN, SSDPTarget
from gossip.upnp.model.descriptor import Device, Service
from gossip.upnp.resource import UPnPDevice

log = logging.getLogger(__name__)


async def listen(device: Device):
    async with SSDPDevice(UPnPDevice(device)):
        await asyncio.sleep(3600)


if __name__ == "__main__":
    # Initialize the device we're currently using.
    not_found = URI.parse("/ssdp/notfound")
    device = Device(
        SSDPTarget.device_type("MediaRenderer"),
        friendlyName="Dekbook Pro",
        manufacturer="Apple, Inc.",
        modelName="Macbook Pro, 13-inch (2013)",
        UDN=URI.uuid(UUID(int=uuid.getnode())),
        serviceList=(Service(
            serviceType=SSDPTarget.service_type("dial", domain=MULTISCREEN_DOMAIN),
            serviceId=SSDPTarget.service_id("dial", domain=MULTISCREEN_DOMAIN),
            controlURL=not_found,
            eventSubURL=not_found,
            scpdURL=not_found,
        ),)
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    asyncio.run(listen(device), debug=True)
