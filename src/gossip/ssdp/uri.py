import logging
from ipaddress import IPv4Address
from typing import NamedTuple, Self, override
from uuid import UUID

from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint

SSDP_DOMAIN = "schemas.upnp.org"
UPNP_DOMAIN = "upnp.org"

SSDP_IP_ADDRESS = IPv4Address("239.255.255.250")
SSDP_PORT: int = 1900
SSDP_HOST = Endpoint(SSDP_IP_ADDRESS, SSDP_PORT)

log = logging.getLogger(__name__)


class SSDPDeviceTarget(URI):
    """Some convenience methods for generating SSDP target strings."""

    @classmethod
    def root(cls) -> Self:
        """UPnP root devices only."""
        return cls.upnp("rootdevice")

    @classmethod
    def device_type(cls, type: str, version: int | None = None, domain: str = SSDP_DOMAIN) -> Self:
        """Any device of a given type, with optional version/domain."""
        if version is None:
            version = 1
        stripped_domain = domain.replace(".", "-")
        return cls.urn(":".join((stripped_domain, "device", type, str(version))))


class SSDPTarget(SSDPDeviceTarget):
    @classmethod
    def all(cls) -> Self:
        """All devices."""
        return cls.ssdp("all")

    @classmethod
    def service_type(cls, type: str, version: int | None = None, domain: str = SSDP_DOMAIN) -> Self:
        """Any service of a type, with version/domain."""
        if version is None:
            version = 1
        stripped_domain = domain.replace(".", "-")
        return cls.urn(":".join((stripped_domain, "service", type, str(version))))

    @classmethod
    def service_id(cls, id: str, domain: str = UPNP_DOMAIN) -> Self:
        """Search for a specific service by ID."""
        stripped_domain = domain.replace(".", "-")
        return cls.urn(":".join((stripped_domain, "serviceId", id)))


class UniqueServiceName(NamedTuple):
    """The Unique Service Name (USN) for the service."""

    UDN: URI
    target: URI | None = None

    @override
    def __repr__(self):
        """Overriding the default repr because it's too verbose for SSDP."""
        return str(self)

    @override
    def __str__(self):
        """Returns the string format of this USN.

        This isn't _technically_ a URI, it's two URIs joined by a
        double-semicolon. This does that, optionally filtering out an empty
        target in the case of the USN being simply `uuid:<uuid>`.
        """
        args = filter(None, (self.UDN, self.target))
        return "::".join(map(str, args))

    @classmethod
    def parse(cls, string: str) -> Self:
        parts = string.split("::", 1)

        if len(parts) > 1:
            uuid_part, target_part = parts
            device_target = SSDPDeviceTarget.parse(target_part)
        else:
            uuid_part = parts[0]
            device_target = None
        uuid_suffix = uuid_part.replace("-", "")[-32:]

        return cls(SSDPTarget.uuid(UUID(uuid_suffix)), device_target)
