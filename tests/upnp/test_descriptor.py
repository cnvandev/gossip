from asyncio import run as run_async
from pathlib import Path
from uuid import UUID

from gossip.internet.uri import URI
from gossip.network.serializer import BufferedReader
from gossip.ssdp.uri import SSDPTarget, UniqueServiceName
from gossip.upnp.model.descriptor import Device

from .descriptor import DummyDevice, DummyService

DATA_DIR = Path(__file__).parent / "data"

ROOT_UDN = UUID("11111111-1111-1111-1111-111111111111")
CHILD_UDN = UUID("22222222-2222-2222-2222-222222222222")


class TestServiceTargets:
    """The SSDP target(s) a `Service` should be advertised/matched under."""

    def test_targets_is_just_the_service_type(self):
        """A service's only target is its own service type."""
        service = DummyService("myservice")
        assert service.targets() == (service.serviceType,)


class TestDeviceExtensionsIn:
    """Querying a `Device`'s vendor XML extensions by namespace."""

    def _device_with_dlna_extensions(self) -> Device:
        xml = (DATA_DIR / "device_with_dlna_extensions.xml").read_text()
        return run_async(Device.from_xml(BufferedReader.for_bytes(xml.encode())))

    def test_returns_elements_in_the_matching_namespace(self):
        """An extension element from the requested namespace is returned,
        with its text content intact."""
        device = self._device_with_dlna_extensions()
        (extension,) = device.extensions_in(URI.urn("schemas-dlna-org:device-1-0"))
        assert extension.text == "DMS-1.50"

    def test_returns_empty_for_a_namespace_with_no_extensions(self):
        """A namespace the device has no extensions in returns an empty
        tuple rather than raising."""
        device = self._device_with_dlna_extensions()
        assert device.extensions_in(URI.urn("schemas-other-org:device-1-0")) == ()

    def test_device_with_no_extensions_returns_empty(self):
        """A device parsed with no vendor extensions at all has an empty
        `extensions` tuple to query."""
        device = DummyDevice(udn=ROOT_UDN)
        assert device.extensions_in(URI.urn("schemas-dlna-org:device-1-0")) == ()


class TestDeviceTargets:
    """Building the map from Unique Service Names to SSDP target URIs for a
    device and everything nested under it."""

    def test_leaf_device_yields_root_and_udn_and_type_targets(self):
        """A device with no children or services still yields three
        entries: the root-device target, its bare UDN, and its device
        type."""
        device = DummyDevice("mydevice", udn=ROOT_UDN)
        targets = device.targets()
        assert targets[UniqueServiceName(device.UDN, SSDPTarget.root())] == SSDPTarget.root()
        assert targets[UniqueServiceName(device.UDN, None)] == device.UDN
        assert targets[UniqueServiceName(device.UDN, device.deviceType)] == device.deviceType
        assert len(targets) == 3

    def test_services_add_a_target_per_service_type(self):
        """Each service under a device contributes its own USN entry keyed
        by the device's UDN and the service's type."""
        service = DummyService("myservice")
        device = DummyDevice("mydevice", udn=ROOT_UDN, serviceList=(service,))
        targets = device.targets()
        assert targets[UniqueServiceName(device.UDN, service.serviceType)] == service.serviceType
        assert len(targets) == 4

    def test_embedded_devices_are_visited_and_included(self):
        """A child device nested under the root contributes its own UDN and
        type targets, but the root-device target is only ever emitted for
        the top-level device that `targets()` was called on."""
        child = DummyDevice("childdevice", udn=CHILD_UDN)
        root = DummyDevice("rootdevice", udn=ROOT_UDN, deviceList=(child,))
        targets = root.targets()

        assert targets[UniqueServiceName(root.UDN, SSDPTarget.root())] == SSDPTarget.root()
        assert targets[UniqueServiceName(root.UDN, None)] == root.UDN
        assert targets[UniqueServiceName(root.UDN, root.deviceType)] == root.deviceType
        assert targets[UniqueServiceName(child.UDN, None)] == child.UDN
        assert targets[UniqueServiceName(child.UDN, child.deviceType)] == child.deviceType
        assert UniqueServiceName(child.UDN, SSDPTarget.root()) not in targets
        assert len(targets) == 5

    def test_embedded_devices_services_are_included(self):
        """A service on an embedded (non-root) device is reachable in the
        target map too, keyed by that embedded device's own UDN."""
        child_service = DummyService("childservice")
        child = DummyDevice("childdevice", udn=CHILD_UDN, serviceList=(child_service,))
        root = DummyDevice("rootdevice", udn=ROOT_UDN, deviceList=(child,))
        targets = root.targets()
        assert targets[UniqueServiceName(child.UDN, child_service.serviceType)] == child_service.serviceType


class TestDeviceConfigId:
    """Deriving a UPnP `configId` from the device description's content."""

    def test_config_id_is_a_24_bit_integer(self):
        """Per the UPnP spec, `configId` fits within 3 bytes."""
        device = DummyDevice(udn=ROOT_UDN)
        assert 0 <= device.config_id() < 2**24

    def test_config_id_is_deterministic(self):
        """The same device description always hashes to the same
        `configId`."""
        device = DummyDevice(udn=ROOT_UDN)
        assert device.config_id() == device.config_id()

    def test_config_id_changes_when_content_changes(self):
        """A different device description hashes to a (near-certainly)
        different `configId`."""
        first = DummyDevice("mydevice", udn=ROOT_UDN)
        second = DummyDevice("otherdevice", udn=ROOT_UDN)
        assert first.config_id() != second.config_id()
