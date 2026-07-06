import logging
from collections.abc import Buffer
from typing import Self, override

from xsdata.formats.converter import Converter, converter
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer

from gossip.internet.mime import MediaType
from gossip.internet.uri import URI
from gossip.ssdp.uri import SSDPDeviceTarget, SSDPTarget
from gossip.upnp.uri import ESCAPED_SCHEMA

log = logging.getLogger(__name__)


class URIConverter(Converter):
    """A serializer/deserializer for URI objects.

    It uses `URI.parse()` to parse, it's `urllib.parse.urlparse()` internally.
    """

    @override
    def deserialize(self, value: str, **_) -> URI:
        return URI.parse(value)

    @override
    def serialize(self, value: URI, **_) -> str:
        return str(value)


class MediaTypeConverter(Converter):
    """A serializer/deserializer for `MediaType` objects, using the class's
    `MediaType.parse()` method."""

    @override
    def deserialize(self, value: str, **_) -> MediaType:
        return MediaType.parse(value)

    @override
    def serialize(self, value: MediaType, **_) -> str:
        return str(value)


converter.register_converter(URI, URIConverter())
converter.register_converter(SSDPTarget, URIConverter())
converter.register_converter(SSDPDeviceTarget, URIConverter())
converter.register_converter(MediaType, MediaTypeConverter())


context = XmlContext()
PARSER = XmlParser(context=context)
SERIALIZER = XmlSerializer(context=context)

# This is the namespace map for UPnP XML documents, defaulting to the UPnP
# device namespace.
UPNP_DEVICE_NS = URI.urn(f"{ESCAPED_SCHEMA}:device-1-0")
UPNP_NS_MAP: dict[str | None, str] = {
    None: str(UPNP_DEVICE_NS),
}


class XMLSerializable:
    """Base class for UPnP classes that need to be serialized to/from XML.

    Subclasses get `to_xml()` and `from_xml()` methods to serialize/deserialize.
    """

    def to_xml(self) -> str:
        return SERIALIZER.render(self, ns_map=UPNP_NS_MAP)

    @classmethod
    def from_xml(cls, buffer: Buffer) -> Self:
        return PARSER.from_bytes(bytes(buffer), cls, ns_map=UPNP_NS_MAP)
