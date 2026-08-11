import hashlib
import logging
from collections import deque
from collections.abc import MutableMapping
from dataclasses import dataclass, field

from xsdata.formats.dataclass.models.generics import AnyElement

from gossip.internet.mime import MediaType
from gossip.internet.uri import URI
from gossip.ssdp.uri import SSDPDeviceTarget, SSDPTarget, UniqueServiceName
from gossip.upnp.xml import UPNP_DEVICE_NS, XMLSerializable

log = logging.getLogger(__name__)


@dataclass
class Icon(XMLSerializable):
    """Icon to depict device in a control point UI. Is allowed to have a
    different value depending on language requested (see ACCEPT-LANGUAGE and
    CONTENT-LANGUAGE header fields). Icon sizes to support are
    vendor-specific.
    """

    class Meta:
        name: str = "icon"
        namespace: str = str(UPNP_DEVICE_NS)

    """Icon's MIME type (see RFC 2045, 2046, and 2387). Single MIME image
    type. At least one icon should be of type `image/png` (Portable Network
    Graphics, see IETF RFC 2083).
    """
    mimetype: MediaType

    """Horizontal dimension of icon in pixels."""
    width: int

    """Vertical dimension of icon in pixels."""
    height: int

    """Number of color bits per pixel."""
    depth: int

    """Pointer to icon image. (XML does not support direct embedding of
    binary data. See note below.) Retrieved via HTTP. Shall be relative to
    the URL at which the device description is located in accordance with
    clause 5 of RFC 3986. Specified by UPnP vendor.
    """
    url: URI


@dataclass(frozen=True)
class Service(XMLSerializable):
    """A service that a device offers."""

    class Meta:
        name: str = "service"
        namespace: str = str(UPNP_DEVICE_NS)

    """UPnP service type. Shall not contain a hash character (#, 23 Hex in
    UTF-8).

    - For standard service types defined by a UPnP Forum working committee,
    shall begin with `urn:schemas-upnp-org:service:` followed by the
    standardized service type suffix, colon, and an integer service version
    i.e. `urn:schemas-upnp-org:device:serviceType:ver`. The highest
    supported version of the service type shall be specified.
    - For non-standard service types specified by UPnP vendors, shall begin
    with `urn:`, followed by a Vendor Domain Name, followed by `:service:`,
    followed by a service type suffix, colon, and an integer service
    version, i.e. `urn:domain-name:service:serviceType:ver`. Period
    characters in the Vendor Domain Name shall be replaced with hyphens in
    accordance with RFC 2141. The highest supported version of the service
    type shall be specified.

    The service type suffix defined by a UPnP Forum working committee or
    specified by a UPnP vendor shall be <= 64 characters, not counting the
    version suffix and separating colon.
    """
    serviceType: URI = field(metadata=dict(type="Element"))

    """Service identifier. Shall be unique within this device description.

    - For standard services defined by a UPnP Forum working committee, shall
    begin with `urn:upnp-org:serviceId:` followed by a service ID suffix
    i.e. `urn:upnp-org:serviceId:serviceID`. If this instance of the
    specified service type (i.e. the `<serviceType>` element above)
    corresponds to one of the services defined by the specified device type
    (i.e. the `<deviceType>` element above), then the value of the service
    ID suffix shall be the service ID defined by the device type for this
    instance of the service. Otherwise, the value of the service ID suffix
    is vendor defined. (Note that upnp-org is used instead of
    schemas-upnp-org in this case because an XML schema is not defined for
    each service ID.)
    - For non-standard services specified by UPnP vendors, shall begin with
    `urn:`, followed by a Vendor Domain Name, followed by `:serviceId:`,
    followed by a service ID suffix,
    i.e., `urn:domain-name:serviceId:serviceID`. If this instance of the
    specified service type (i.e. the `<serviceType>` element above)
    corresponds to one of the services defined by the specified device type
    (i.e. the <deviceType> element above), then the value of the service ID
    suffix shall be the service ID defined by the device type for this
    instance of the service. Period characters in the Vendor Domain Name
    shall be replaced with hyphens in accordance with RFC 2141.

    The service ID suffix defined by a UPnP Forum working committee or
    specified by a UPnP vendor shall be <= 64 characters.
    """
    serviceId: URI = field(metadata=dict(type="Element"))

    """URL for service description. Shall be relative to the URL at which
    the device description is located in accordance with clause 5 of
    RFC 3986. Specified by UPnP vendor.
    """
    scpdURL: URI = field(metadata=dict(name="SCPDURL", type="Element"))

    """URL for control. Shall be relative to the URL at which the device
    description is located in accordance with clause 5 of RFC 3986.
    Specified by UPnP vendor.
    """
    controlURL: URI = field(metadata=dict(type="Element"))

    """URL for eventing. Shall be relative to the URL at which the device
    description is located in accordance with clause 5 of RFC 3986. shall be
    unique within the device; any two services shall not have the same URL
    for eventing. If the service has no evented variables, this element
    shall be present but shall be empty
    (i.e., `<eventSubURL></eventSubURL>`.)
    Specified by UPnP vendor.
    """
    eventSubURL: URI = field(metadata=dict(type="Element"))

    def targets(self):
        return (self.serviceType,)


@dataclass(frozen=True)
class Device(XMLSerializable):
    """A device, according to SSDP."""

    class Meta:
        name: str = "device"
        namespace: str = str(UPNP_DEVICE_NS)

    """UPnP device type.

    - For standard devices defined by a UPnP Forum working committee, shall
      begin with `urn:schemas-upnp-org:device:` followed by the standardized
      device type suffix, a colon, and an integer device version i.e.
      `urn:schemas-upnp-org:device:deviceType:ver`. The highest supported
      version of the device type shall be specified.
    - For non-standard devices specified by UPnP vendors, shall begin with
      `urn:`, followed by a Vendor Domain Name, followed by `:device:`, followed
      by a device type suffix, colon, and an integer version, i.e.,
      `urn:domain-name:device:deviceType:ver`. Period characters in the Vendor
      Domain Name shall be replaced with hyphens in accordance with RFC 2141.
      The highest supported version of the device type shall be specified.

    The device type suffix defined by a UPnP Forum working committee or
    specified by a UPnP vendor shall be <= 64 chars, not counting the version
    suffix and separating colon.
    """
    deviceType: SSDPDeviceTarget = field(metadata=dict(type="Element"))

    """Short description for end user. Is allowed to be localized
    (see ACCEPT-LANGUAGE and CONTENT-LANGUAGE header fields). Specified by UPnP
    vendor. Should be < 64 characters.
    """
    friendlyName: str = field(metadata=dict(type="Element"))

    """Manufacturer's name. Is allowed to be localized (see
    ACCEPT-LANGUAGE and CONTENT-LANGUAGE header fields). Specified by UPnP
    vendor. Should be < 64 characters.
    """
    manufacturer: str = field(metadata=dict(type="Element"))

    """Model name. Is allowed to be localized (see ACCEPT-LANGUAGE and
    CONTENT-LANGUAGE header fields). Specified by UPnP vendor. Should be < 32
    characters.
    """
    modelName: str = field(metadata=dict(type="Element"))

    """Unique Device Name. Universally-unique identifier for the device, whether
    root or embedded. Shall be the same over time for a specific device instance
    (i.e., shall survive reboots). Shall match the field value of the NT header
    field in device discovery messages. shall match the prefix of the USN header
    field in all discovery messages. Shall begin with `uuid:` followed by a UUID
    suffix specified by a UPnP vendor.
    """
    UDN: URI = field(metadata=dict(type="Element"))

    """Web site for Manufacturer. Is allowed to have a different value depending
    on language requested (see ACCEPT-LANGUAGE and CONTENT-LANGUAGE header
    fields). Specified by UPnP vendor.
    """
    manufacturerURL: URI | None = field(default=None, metadata=dict(type="Element"))

    """Long description for end user. Is allowed to be localized
    (see ACCEPT- LANGUAGE and CONTENT-LANGUAGE header fields). Specified by UPnP
    vendor. Should be < 128 characters.
    """
    modelDescription: str | None = field(default=None, metadata=dict(type="Element"))

    """Model number. Is allowed to be localized (see ACCEPT-LANGUAGE and
    CONTENT-LANGUAGE header fields). Specified by UPnP vendor. String. Should be
    < 32 characters.
    """
    modelNumber: str | None = field(default=None, metadata=dict(type="Element"))

    """Web site for model. Is allowed to have a different value depending on
    language requested (see ACCEPT-LANGUAGE and CONTENT-LANGUAGE header fields).
    Specified by UPnP vendor.
    """
    modelURL: URI | None = field(default=None, metadata=dict(type="Element"))

    """Recommended. Serial number. Is allowed to be localized (see
    ACCEPT-LANGUAGE and CONTENT-LANGUAGE header fields). Specified by UPnP
    vendor. Should be < 64 characters."""
    serialNumber: str | None = field(default=None, metadata=dict(type="Element"))

    """Universal Product Code. 12-digit, all-numeric code that identifies the
    consumer package. Managed by the Uniform Code Council. Specified by UPnP
    vendor.
    """
    UPC: str | None = field(default=None, metadata=dict(type="Element"))

    """URL to presentation for device. Shall be relative to the URL at which the
    device description is located in accordance with the rules specified in
    clause 5 of RFC 3986. Specified by UPnP vendor.
    """
    presentationURL: URI | None = field(default=None, metadata=dict(type="Element"))

    """Required if and only if device has one or more icons. Specified by UPnP
    vendor.
    """
    iconList: tuple[Icon, ...] | None = field(default=None, metadata=dict(type="Element", name="icon", wrapper="iconList"))

    """Repeated once for each service defined by a UPnP Forum working committee.
    If UPnP vendor differentiates device by adding additional, standard UPnP
    services, repeated once for each additional service.
    """
    serviceList: tuple[Service, ...] | None = field(default=None, metadata=dict(type="Element", name="service", wrapper="serviceList"))

    """Required if and only if root device has embedded devices. Repeat once for
    each embedded device defined by a UPnP Forum working committee. If UPnP
    vendor differentiates device by embedding additional UPnP devices, repeat
    once for each embedded device. Contains sub elements as defined above for
    root sub element device.
    """
    deviceList: tuple["Device", ...] | None = field(default=None, metadata=dict(type="Element", name="device", wrapper="deviceList"))

    """Vendor extension elements not covered by the UPnP device schema, e.g.
    DLNA's `X_DLNADOC`/`X_DLNACAP`. Kept as raw `AnyElement`s rather than
    modeled explicitly, since vendors add these freely; use `extensions_in()`
    to query them by namespace.
    """
    extensions: tuple[object, ...] = field(default_factory=tuple, metadata=dict(type="Wildcard", namespace="##any"))

    def extensions_in(self, namespace: str | URI) -> tuple[AnyElement, ...]:
        """Returns extension elements belonging to the given XML namespace,
        e.g. DLNA's `urn:schemas-dlna-org:device-1-0`.
        """
        prefix = f"{{{namespace}}}"
        return tuple(extension for extension in self.extensions if extension.qname.startswith(prefix))

    def targets(self) -> MutableMapping[UniqueServiceName, URI]:
        """Returns a dictionary from USNs to SSDP target URLs they match."""
        # The device is a tree structure, so we'll use a deque to iterate over
        # it and any embedded devices we find (recursively).
        devices = deque((self,) + tuple(self.deviceList or tuple()))
        output: MutableMapping[UniqueServiceName, SSDPTarget] = {
            UniqueServiceName(self.UDN, SSDPTarget.root()): SSDPTarget.root(),
        }
        while devices:
            device = devices.popleft()
            output |= {
                UniqueServiceName(device.UDN, None): device.UDN,
                UniqueServiceName(device.UDN, device.deviceType): device.deviceType,
            }

            # Add any devices to the queue, so we can visit them later.
            if device.deviceList is not None:
                devices.extend(device.deviceList)

            # Ways to refer to devices: the device itself (identified by UDN and
            # the root target if applicable), the device's type, and the
            # service types.
            if device.serviceList is not None:
                output |= {UniqueServiceName(device.UDN, service.serviceType): service.serviceType for service in device.serviceList}
        return output

    def config_id(self) -> int:
        body_string = self.to_xml()
        sha256_hash = hashlib.sha256(body_string.encode()).digest()
        return int.from_bytes(sha256_hash[:3], byteorder="big")


@dataclass(frozen=True)
class Version(XMLSerializable):
    """A major.minor version encapsulation."""

    class Meta:
        name: str = "version"
        namespace: str = str(UPNP_DEVICE_NS)

    major: int
    minor: int


@dataclass
class DeviceSpec(XMLSerializable):
    """A response to an SSDP device discovery request."""

    class Meta:
        name: str = "root"
        namespace: str = str(UPNP_DEVICE_NS)

    specVersion: Version = field(metadata=dict(type="Element"))
    device: Device = field(metadata=dict(type="Element"))
    configId: str | None = field(default=None, metadata=dict(type="Attribute"))
    URLBase: URI | None = field(default=None, metadata=dict(type="Element"))
