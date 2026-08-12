"""Synthetic `Device`/`Service` instances for the upnp test suite.

Not a test module - imported by test_descriptor.py.
"""

from uuid import UUID

from gossip.internet.uri import URI
from gossip.ssdp.uri import SSDPDeviceTarget, SSDPTarget
from gossip.upnp.model.descriptor import Device, Service

DEFAULT_UDN = UUID("11111111-1111-1111-1111-111111111111")


class DummyService(Service):
    """A service with synthetic identifiers/URLs for a given service name."""

    def __init__(self, name: str = "myservice"):
        super().__init__(
            serviceType=SSDPTarget.service_type(name),
            serviceId=SSDPTarget.service_id(name),
            scpdURL=URI.parse("/scpd.xml"),
            controlURL=URI.parse("/control"),
            eventSubURL=URI.parse("/event"),
        )


class DummyDevice(Device):
    """A device with synthetic identity fields for a given name/UDN,
    optionally with embedded devices/services."""

    def __init__(
        self,
        name: str = "device",
        udn: UUID = DEFAULT_UDN,
        deviceList: tuple[Device, ...] | None = None,
        serviceList: tuple[Service, ...] | None = None,
    ):
        super().__init__(
            deviceType=SSDPDeviceTarget.device_type(name),
            friendlyName=name,
            manufacturer="Acme",
            modelName="Widget",
            UDN=URI.uuid(udn),
            deviceList=deviceList,
            serviceList=serviceList,
        )
