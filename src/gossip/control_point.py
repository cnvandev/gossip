import asyncio
import logging
import sys

from gossip.http.client import HTTPClient
from gossip.internet.uri import URI
from gossip.ssdp.control_point import SSDPControlPoint
from gossip.ssdp.uri import SSDPTarget
from gossip.upnp.model.descriptor import DeviceSpec
from gossip.upnp.resource import UPnPDevice

log = logging.getLogger(__name__)


async def client():
    control_point = SSDPControlPoint("Dekbook Pro")
    http_client = HTTPClient()
    async with control_point as session:
        searcher = await session.broadcast_search(SSDPTarget.all())
        results = {}
        async with searcher.stream() as search:
            async for response in search:
                log.debug(response.headers.get("USN"))
                location = response.headers.get("Location")
                target = response.headers.get("ST")
                if location:
                    device_uri = URI.parse(location)
                    if device_uri not in results:
                        log.debug("Fetching %s @ %s", target, device_uri)
                        device_response = await http_client.get(device_uri)

                        if device_response is not None and device_response.status.is_success and device_response.body is not None:
                            device = DeviceSpec.from_xml(device_response.body).device
                            log.info("Found %s", UPnPDevice(device))
                            results[device_uri] = device_response
                    else:
                        log.debug("Skipping %s, already seen", device_uri)


if __name__ == "__main__":
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    asyncio.run(client(), debug=True)
