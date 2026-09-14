from uuid import UUID

from gossip.internet.uri import URI
from gossip.ssdp.uri import SSDPDeviceTarget, SSDPTarget, UniqueServiceName


class TestSSDPDeviceTarget:
    """The `urn:`-building factories shared by every SSDP target: the
    well-known root-device target, and any device type by name."""

    def test_root(self):
        """The well-known root-device target renders as
        `upnp:rootdevice`."""
        assert str(SSDPDeviceTarget.root()) == "upnp:rootdevice"

    def test_device_type_default_domain_and_version(self):
        """A device type with no domain/version given defaults to the
        standard UPnP schema domain and version `1`."""
        target = SSDPDeviceTarget.device_type("MediaRenderer")
        assert str(target) == "urn:schemas-upnp-org:device:MediaRenderer:1"

    def test_device_type_custom_domain_and_version(self):
        """An explicit domain and version override the defaults, with dots
        in the domain replaced by hyphens."""
        target = SSDPDeviceTarget.device_type("Widget", version=2, domain="example.com")
        assert str(target) == "urn:example-com:device:Widget:2"


class TestSSDPTarget:
    """The additional `urn:`-building factories for services, plus the
    `ssdp:all` wildcard search target."""

    def test_all(self):
        """The wildcard search target renders as `ssdp:all`."""
        assert str(SSDPTarget.all()) == "ssdp:all"

    def test_service_type_default_domain_and_version(self):
        """A service type with no version given defaults to version `1`."""
        target = SSDPTarget.service_type("dial", domain="dial.multiscreen.org")
        assert str(target) == "urn:dial-multiscreen-org:service:dial:1"

    def test_service_id(self):
        """A service-ID target is built from just the domain and ID, with
        no type/version component."""
        target = SSDPTarget.service_id("dial", domain="dial.multiscreen.org")
        assert str(target) == "urn:dial-multiscreen-org:serviceId:dial"


class TestSSDPTargetCovers:
    """`SSDPTarget.covers()` overrides `URI.covers()`'s exact-equality
    default with an `ssdp:all` wildcard that covers every target; any
    other target falls back to that same exact-equality default. The
    comparison operators (`<=`, `>=`, `<`, `>`) aren't redefined here -
    they're inherited from `URI` and dispatch to this override."""

    def test_all_covers_any_target(self):
        """`ssdp:all` covers any other target."""
        assert SSDPTarget.all().covers(SSDPTarget.root())

    def test_all_covers_itself(self):
        """`ssdp:all` covers itself."""
        assert SSDPTarget.all().covers(SSDPTarget.all())

    def test_a_concrete_target_falls_back_to_exact_equality(self):
        """A concrete (non-wildcard) target covers an equal target, but not
        a different one - the inherited `URI.covers()` behavior."""
        assert SSDPTarget.device_type("Foo").covers(SSDPTarget.device_type("Foo"))
        assert not SSDPTarget.root().covers(SSDPTarget.device_type("Foo"))

    def test_le_dispatches_to_the_wildcard_override(self):
        """`<=` (inherited from `URI`, unchanged) dispatches to
        `SSDPTarget.covers()` - any target is `<=` the `ssdp:all`
        wildcard, but not the other way around."""
        assert SSDPTarget.root() <= SSDPTarget.all()
        assert not (SSDPTarget.all() <= SSDPTarget.root())

    def test_ge_dispatches_to_the_wildcard_override(self):
        """`>=` (inherited from `URI`, unchanged) dispatches to
        `SSDPTarget.covers()` - the `ssdp:all` wildcard is `>=` any
        target, but not the other way around."""
        assert SSDPTarget.all() >= SSDPTarget.root()
        assert not (SSDPTarget.root() >= SSDPTarget.all())

    def test_lt_is_true_for_a_concrete_target_against_the_wildcard(self):
        """A concrete target is strictly `<` the wildcard: the wildcard
        covers it, but it doesn't cover the wildcard back."""
        assert SSDPTarget.root() < SSDPTarget.all()

    def test_gt_is_true_for_the_wildcard_against_a_concrete_target(self):
        """The wildcard is strictly `>` any concrete target."""
        assert SSDPTarget.all() > SSDPTarget.root()


class TestUniqueServiceName:
    """Converting a USN to and from its `UDN::target` (or bare `UDN`)
    string form."""

    def test_str_joins_udn_and_target(self):
        """A USN with both a UDN and a target joins them with `::`."""
        udn = URI.uuid(UUID(int=1))
        usn = UniqueServiceName(udn, SSDPTarget.root())
        assert str(usn) == f"{udn}::upnp:rootdevice"

    def test_str_omits_empty_target(self):
        """A USN with no target renders as just the bare UDN, with no
        trailing `::`."""
        udn = URI.uuid(UUID(int=1))
        usn = UniqueServiceName(udn, None)
        assert str(usn) == str(udn)

    def test_repr_matches_str(self):
        """`repr()` delegates to the same `UDN::target` form as `str()`,
        overriding the verbose default `NamedTuple` repr."""
        udn = URI.uuid(UUID(int=1))
        usn = UniqueServiceName(udn, SSDPTarget.root())
        assert repr(usn) == str(usn)

    def test_parse_round_trips_with_target(self):
        """Parsing a USN's string form, including a target, reproduces the
        original USN."""
        udn = URI.uuid(UUID(int=0x1234))
        usn = UniqueServiceName(udn, SSDPTarget.root())
        assert UniqueServiceName.parse(str(usn)) == usn

    def test_parse_round_trips_without_target(self):
        """Parsing a USN's string form, with no target, reproduces the
        original USN."""
        udn = URI.uuid(UUID(int=0x1234))
        usn = UniqueServiceName(udn, None)
        assert UniqueServiceName.parse(str(usn)) == usn

    def test_parse_round_trips_a_real_uuid_with_hex_letters(self):
        """Parsing works for a genuine random-looking UUID, not just the
        small sequential ones `UUID(int=...)` produces - the dash-stripping
        logic that recovers the 32-character hex suffix isn't accidentally
        relying on those being all-digits."""
        udn = URI.uuid(UUID("a1b2c3d4-e5f6-4789-a1b2-c3d4e5f67890"))
        usn = UniqueServiceName(udn, SSDPTarget.root())
        assert UniqueServiceName.parse(str(usn)) == usn

    def test_parse_accepts_a_uuid_without_the_uuid_scheme_prefix(self):
        """A UDN parsed from a bare UUID string (no `uuid:` prefix) resolves
        to the same UDN as one parsed with the prefix - the parser strips
        dashes and takes the last 32 hex characters, which works whether or
        not the scheme prefix is there."""
        value = UUID("a1b2c3d4-e5f6-4789-a1b2-c3d4e5f67890")
        assert UniqueServiceName.parse(str(value)).UDN == URI.uuid(value)
