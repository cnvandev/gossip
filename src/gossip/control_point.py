import asyncio
import logging
import sys

from gossip.internet.uri import URI
from gossip.ssdp.control_point import SSDPControlPoint
from gossip.ssdp.uri import SSDPTarget
from gossip.upnp.model.descriptor import DeviceSpec

log = logging.getLogger(__name__)


async def client(control_point: SSDPControlPoint):
    async with control_point as session:
        searcher = await session.broadcast_search(SSDPTarget.device_type("Basic"))
        results = {}
        async with searcher.stream() as search:
            async for response in search:
                log.debug(response.headers.get("USN"))
                # location = response.headers().get("Location")
                # type = response.headers().get("ST")
                # if location:
                #     log.debug("Fetching %s @ %s", type, location)
                #     device_uri = URI.parse(location)
                #     if device_uri not in results:
                #         device_response = await ssdp.get(device_uri)
                #         log.debug("Received response from %s", device_response)

                #         if device_response is not None:
                #             if device_response.status.is_successful() and device_response.body is not None:
                #                 log.info(DeviceSpec.from_xml(device_response.body).device.deviceType)
                #                 results[device_uri] = device_response
                #     else:
                #         log.debug("Skipping %s, already seen", device_uri)


if __name__ == "__main__":
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    control_point = SSDPControlPoint("Dekbook Pro")
    asyncio.run(client(control_point), debug=True)
