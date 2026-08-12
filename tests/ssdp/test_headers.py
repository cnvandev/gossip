from gossip.ssdp import headers
from gossip.ssdp.headers import ExtensionHeader


class TestExtensionHeaderString:
    """Formatting an `ExtensionHeader` as the upper-cased `KEY.DOMAIN`
    header name used on the wire."""

    def test_str_joins_key_and_domain_uppercased(self):
        """The key and domain are joined with a dot and upper-cased,
        regardless of the casing they were given in."""
        assert str(ExtensionHeader("tcpport", "upnp.org")) == "TCPPORT.UPNP.ORG"

    def test_str_preserves_multi_label_domain(self):
        """A domain with more than one label keeps all of its dots."""
        assert str(ExtensionHeader("foo", "bar.example.com")) == "FOO.BAR.EXAMPLE.COM"


class TestExtensionHeaderConstants:
    """The module's predefined SSDP extension headers, each scoped to the
    UPnP domain."""

    def test_known_headers_render_as_expected_wire_names(self):
        """Each predefined header renders to the `KEY.UPNP.ORG` form UPnP
        control points expect."""
        assert str(headers.TCP_PORT) == "TCPPORT.UPNP.ORG"
        assert str(headers.BOOT_ID) == "BOOTID.UPNP.ORG"
        assert str(headers.NEXT_BOOT_ID) == "NEXTBOOTID.UPNP.ORG"
        assert str(headers.CONFIG_ID) == "CONFIGID.UPNP.ORG"
        assert str(headers.SEARCH_PORT) == "SEARCHPORT.UPNP.ORG"
        assert str(headers.SECURE_LOCATION) == "SECURELOCATION.UPNP.ORG"
        assert str(headers.CPFN) == "CPFN.UPNP.ORG"
        assert str(headers.CPUUID) == "CPUUID.UPNP.ORG"
