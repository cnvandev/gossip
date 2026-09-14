from uuid import UUID

from gossip.internet.uri import URI
from gossip.ssdp.headers import BOOT_ID, CONFIG_ID
from gossip.ssdp.uri import SSDPTarget
from gossip.upnp.model.descriptor import Version
from gossip.upnp.resource import UPnPDevice

from .descriptor import DummyDevice

UDN = UUID("11111111-1111-1111-1111-111111111111")


class TestUPnPDeviceConstruction:
    """Building a `UPnPDevice` `ResourceCollection` from a `Device` -
    derives its search predicate and per-target data straight from the
    device's own `targets()`."""

    def test_st_predicate_options_are_every_device_target(self):
        """The `ST` predicate's options are every device target."""
        device = DummyDevice("mydevice", udn=UDN)
        resource = UPnPDevice(device)
        options = resource.predicates["ST"].options
        for target in device.targets().values():
            assert SSDPTarget.parse(str(target)) in options

    def test_st_predicate_accepts_ssdp_all_for_every_target(self):
        """A search for `ssdp:all` matches every device target, since
        `SSDPTarget.covers()` treats it as a wildcard rather than a
        target of its own."""
        device = DummyDevice("mydevice", udn=UDN)
        resource = UPnPDevice(device)
        predicate = resource.predicates["ST"]
        accepted = {option for option, _ in predicate.accepts(str(SSDPTarget.all()))}
        assert accepted == set(predicate.options)

    def test_data_has_an_entry_per_target_with_config_boot_and_usn(self):
        """`data` has an entry per target, with config ID, boot ID, and USN."""
        device = DummyDevice("mydevice", udn=UDN)
        resource = UPnPDevice(device)
        for usn, target in device.targets().items():
            assert resource.data[str(target)] == {
                str(CONFIG_ID): str(device.config_id()),
                str(BOOT_ID): "1",
                "USN": str(usn),
            }

    def test_device_is_stored_as_given(self):
        """`device` is the same object passed in."""
        device = DummyDevice("mydevice", udn=UDN)
        assert UPnPDevice(device).device is device


class TestUPnPDeviceCompactType:
    """`UPnPDevice.compact_type()` - a short `type:name[:version]` form of the
    device's type, omitting the standard UPnP schema domain and a version
    of `1` unless they're non-default."""

    def test_standard_domain_and_version_one_omits_both(self):
        """The standard domain and version `1` are both omitted."""
        device = DummyDevice("mydevice", udn=UDN)
        assert UPnPDevice(device).compact_type() == "device:mydevice"

    def test_nonstandard_domain_is_prefixed(self):
        """A nonstandard domain is prefixed to the type."""
        device = DummyDevice("Widget", udn=UDN, domain="example.com")
        assert UPnPDevice(device).compact_type() == "example-com:device:Widget"

    def test_version_greater_than_one_is_appended(self):
        """A version greater than `1` is appended to the type."""
        device = DummyDevice("Widget", udn=UDN, version=2)
        assert UPnPDevice(device).compact_type() == "device:Widget:2"


class TestUPnPDeviceRepr:
    """`UPnPDevice.__repr__()` - a compact summary naming the device's
    compact type, friendly name, and UDN."""

    def test_includes_compact_type_friendly_name_and_udn(self):
        """The rendered text includes the compact type, name, and UDN."""
        device = DummyDevice("mydevice", udn=UDN)
        resource = UPnPDevice(device)
        assert repr(resource) == f'UPnPDevice("device:mydevice", "mydevice", {device.UDN})'


class TestUPnPDeviceGetSpec:
    """`UPnPDevice.get_spec()` - wraps the device in the `DeviceSpec` root
    element that gets serialized to the device description XML."""

    def test_spec_version_is_always_upnp_2_0(self):
        """`specVersion` is always UPnP 2.0."""
        device = DummyDevice("mydevice", udn=UDN)
        spec = UPnPDevice(device).get_spec(url_base=None)
        assert spec.specVersion == Version(2, 0)

    def test_device_is_the_wrapped_device(self):
        """`device` is the same device the `UPnPDevice` wraps."""
        device = DummyDevice("mydevice", udn=UDN)
        spec = UPnPDevice(device).get_spec(url_base=None)
        assert spec.device is device

    def test_config_id_matches_the_devices_own(self):
        """`configId` matches the device's own `config_id()`."""
        device = DummyDevice("mydevice", udn=UDN)
        spec = UPnPDevice(device).get_spec(url_base=None)
        assert spec.configId == str(device.config_id())

    def test_url_base_is_passed_through_as_given(self):
        """`URLBase` is the given `url_base`, unchanged."""
        device = DummyDevice("mydevice", udn=UDN)
        url_base = URI.parse("http://10.0.0.1:80/")
        spec = UPnPDevice(device).get_spec(url_base=url_base)
        assert spec.URLBase == url_base


class TestUPnPDeviceRepresent:
    """`UPnPDevice.represent()` - serializes the device's `DeviceSpec` to
    XML bytes, for a `GET`/`HEAD` on its description document."""

    async def test_returns_the_specs_xml_as_the_body(self):
        """The body is the spec's serialized XML, with matching metadata."""
        device = DummyDevice("mydevice", udn=UDN)
        resource = UPnPDevice(device)
        exact_uri = URI.parse("http://10.0.0.1:80/device.xml")
        expected = resource.get_spec(url_base=exact_uri).to_xml().encode("utf-8")

        body, metadata = await resource.represent(exact_uri, {})
        assert await body.read() == expected
        assert metadata == {"Content-Type": "application/xml", "Content-Length": str(len(expected))}

    async def test_uses_the_requested_uri_as_the_specs_url_base(self):
        """The requested URI becomes the spec's `URLBase`."""
        device = DummyDevice("mydevice", udn=UDN)
        resource = UPnPDevice(device)
        exact_uri = URI.parse("http://10.0.0.1:80/device.xml")
        body, _metadata = await resource.represent(exact_uri, {})
        xml = (await body.read()).decode("utf-8")
        assert str(exact_uri) in xml


class TestUPnPDeviceOptions:
    """`UPnPDevice.options()` - a device's descriptor is only ever
    fetched, never written to."""

    async def test_only_allows_get_and_head(self):
        """`Allow` doesn't include `PUT`/`PATCH`/`DELETE` - a descriptor
        document is only ever fetched, never written to."""
        device = DummyDevice("mydevice", udn=UDN)
        resource = UPnPDevice(device)
        options = await resource.options(URI.parse("/device.xml"), {})
        assert options == {"Allow": "GET, HEAD, OPTIONS, CONNECT, TRACE"}
