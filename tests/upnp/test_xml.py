from asyncio import run as run_async

from gossip.internet.mime import MediaType
from gossip.internet.uri import URI
from gossip.network.serializer import BufferedReader
from gossip.upnp.model.descriptor import Icon, Version
from gossip.upnp.xml import MediaTypeConverter, URIConverter


class TestURIConverter:
    """Converting between `URI` objects and their string form, for xsdata's
    XML (de)serialization."""

    def test_deserialize_parses_a_uri(self):
        """Deserializing a string produces a `URI` equal to parsing it
        directly."""
        converter = URIConverter()
        assert converter.deserialize("http://example.com/foo") == URI.parse("http://example.com/foo")

    def test_serialize_returns_the_uri_string_form(self):
        """Serializing a `URI` returns its string form."""
        converter = URIConverter()
        uri = URI.parse("http://example.com/foo")
        assert converter.serialize(uri) == str(uri)


class TestMediaTypeConverter:
    """Converting between `MediaType` objects and their string form, for
    xsdata's XML (de)serialization."""

    def test_deserialize_parses_a_media_type(self):
        """Deserializing a `type/subtype` string produces the matching
        `MediaType`."""
        converter = MediaTypeConverter()
        assert converter.deserialize("image/png") == MediaType.image("png")

    def test_serialize_returns_the_media_type_string_form(self):
        """Serializing a `MediaType` returns its `type/subtype` string
        form."""
        converter = MediaTypeConverter()
        assert converter.serialize(MediaType.image("png")) == "image/png"


class TestXMLSerializableRoundTrip:
    """Round-tripping an `XMLSerializable` dataclass through `to_xml()` and
    `from_xml()`."""

    def test_simple_dataclass_round_trips(self):
        """A dataclass of plain fields serializes to XML and parses back to
        an equal instance."""
        version = Version(major=1, minor=0)
        parsed = run_async(Version.from_xml(BufferedReader.for_bytes(version.to_xml().encode())))
        assert parsed == version

    def test_uri_and_media_type_fields_round_trip_as_their_real_types(self):
        """Fields typed as `URI`/`MediaType` come back as those types, not
        as plain strings, since the registered converters are used during
        parsing too."""
        icon = Icon(mimetype=MediaType.image("png"), width=32, height=32, depth=24, url=URI.parse("/icon.png"))
        parsed = run_async(Icon.from_xml(BufferedReader.for_bytes(icon.to_xml().encode())))
        assert parsed == icon
        assert isinstance(parsed.url, URI)
        assert isinstance(parsed.mimetype, MediaType)
