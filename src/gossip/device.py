import asyncio
import logging
import sys
import uuid
from uuid import UUID

from gossip.internet.uri import URI
from gossip.ssdp.device import SSDPDevice
from gossip.ssdp.uri import SSDPTarget
from gossip.upnp.model.descriptor import Device
from gossip.upnp.resource import UPnPDevice

log = logging.getLogger(__name__)


async def listen(device: Device):
    async with SSDPDevice(UPnPDevice(device)):
        await asyncio.sleep(3600)


if __name__ == "__main__":
    # Initialize the device we're currently using.
    device = Device(
        SSDPTarget.device_type("MediaRenderer"),
        friendlyName="Dekbook Pro",
        manufacturer="Apple, Inc.",
        modelName="Macbook Pro, 13-inch (2013)",
        UDN=URI.uuid(UUID(int=uuid.getnode())),
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    asyncio.run(listen(device), debug=True)
