import logging
from asyncio.streams import StreamReader
from collections.abc import Mapping
from typing import Any

from gossip.http.predicate import StringPredicate
from gossip.http.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.network.serializer import BufferedReader
from gossip.ssdp.headers import BOOT_ID, CONFIG_ID
from gossip.ssdp.uri import SSDPTarget
from gossip.upnp.model.descriptor import Device, DeviceSpec, Version
from gossip.upnp.uri import ESCAPED_SCHEMA

log = logging.getLogger(__name__)


class UPnPDevice(ResourceCollection):
    """A device that can be interaced with over UPnP."""

    def __init__(self, device: Device):
        self.device = device

        # We're predicate on searches that match these targets.
        targets = map(str, (target for _, target in device.targets().items()))
        predicates = {
            # We add ssdp:all to the list of targets so that we match requests
            # for all devices.
            "ST": StringPredicate(tuple(targets) + (str(SSDPTarget.all()),)),
        }
        data = {
            str(target): {
                str(CONFIG_ID): str(self.device.config_id()),
                str(BOOT_ID): "1",
                "USN": str(usn),
            }
            for usn, target in self.device.targets().items()
        }
        super().__init__(predicates, data)

    def compact_type(self):
        """Returns a compact, human-readable representation of the device type."""
        escaped_domain, target_type, device_type, version = self.device.deviceType.path.split(":", 3)

        # Unless it's a nonstandard domain and a version greater than 1, we can
        # omit it when displaying the type.
        compact_tuple = (target_type, device_type)
        if escaped_domain != ESCAPED_SCHEMA:
            compact_tuple = (escaped_domain,) + compact_tuple
        if int(version) > 1:
            compact_tuple += (version,)

        return ":".join(compact_tuple)

    def __repr__(self):
        return f'UPnPDevice("{self.compact_type()}", "{self.device.friendlyName}", {self.device.UDN})'

    def get_spec(self, url_base: URI | None) -> DeviceSpec:
        return DeviceSpec(
            specVersion=Version(2, 0),
            device=self.device,
            configId=str(self.device.config_id()),
            URLBase=url_base,
        )

    async def represent(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> tuple[StreamReader | None, Mapping[str, str]]:
        xml = self.get_spec(url_base=exact_uri).to_xml().encode("utf-8")
        return BufferedReader.for_bytes(xml), {
            "Content-Type": "application/xml",
            "Content-Length": str(len(xml)),
        }
