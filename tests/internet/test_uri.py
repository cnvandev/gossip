from uuid import UUID

from gossip.internet.uri import URI


class TestURIParse:
    """Parsing a URI string into its component parts, with and without a
    default scheme to fall back on."""

    def test_parses_components(self):
        """Parsing a URL string splits it into scheme, netloc, path, and
        query."""
        uri = URI.parse("http://example.com/path?x=1")
        assert uri.scheme == "http"
        assert uri.netloc == "example.com"
        assert uri.path == "/path"
        assert uri.query == "x=1"

    def test_str_round_trips(self):
        """Converting a parsed URI back to a string reproduces the original
        string exactly."""
        original = "http://example.com/path?x=1"
        assert str(URI.parse(original)) == original

    def test_default_scheme_is_applied_when_missing(self):
        """A scheme passed to `parse()` fills in for a URL string that
        doesn't specify one of its own."""
        uri = URI.parse("/device.xml", scheme="http")
        assert uri.scheme == "http"
        assert uri.path == "/device.xml"

    def test_no_default_scheme_leaves_scheme_empty(self):
        """Without a default scheme, a schemeless URL string parses with an
        empty scheme rather than raising."""
        uri = URI.parse("/device.xml")
        assert uri.scheme == ""


class TestURIJoin:
    """Resolving a relative reference against a base URI, the same as
    `urllib.parse.urljoin`."""

    def test_join_resolves_relative_path(self):
        """A bare filename joined against a directory-like base resolves
        underneath that directory."""
        base = URI.parse("http://example.com/base/")
        assert str(base.join("device.xml")) == "http://example.com/base/device.xml"

    def test_join_replaces_last_segment_like_urljoin(self):
        """A bare filename joined against a base ending in a filename
        replaces just that last segment, not the whole path."""
        base = URI.parse("http://example.com/base/current")
        assert str(base.join("sibling")) == "http://example.com/base/sibling"

    def test_join_with_absolute_uri_replaces_the_base_entirely(self):
        """Joining against a string that's itself an absolute URI discards
        the base and returns that URI verbatim, rather than concatenating
        it onto the base's path."""
        base = URI.parse("http://example.com/base/current")
        assert str(base.join("http://other.com/foo")) == "http://other.com/foo"

    def test_join_with_root_relative_path_replaces_the_whole_path(self):
        """Joining against a path that starts with `/` replaces the base's
        entire path, keeping only its scheme and netloc - it isn't appended
        underneath whatever directory the base was in."""
        base = URI.parse("http://example.com/base/current")
        assert str(base.join("/other/path")) == "http://example.com/other/path"

    def test_join_with_excess_parent_segments_clamps_at_the_root(self):
        """More `../` segments than the base has directories to climb
        doesn't escape above the root or raise - it just clamps there, the
        same as `urllib.parse.urljoin`."""
        base = URI.parse("http://example.com/base/current")
        assert str(base.join("../../../")) == "http://example.com/"
        assert str(base.join("../../../etc/passwd")) == "http://example.com/etc/passwd"


class TestURIFactories:
    """The scheme-specific factories that build a `URI` for gossip's own
    pseudo-schemes without spelling out `URI.parse(path, scheme=...)` each
    time."""

    def test_http(self):
        """`URI.http()` parses its argument as the path of an `http:` URI."""
        uri = URI.http("/device.xml")
        assert uri.scheme == "http"
        assert uri.path == "/device.xml"

    def test_ssdp(self):
        """`URI.ssdp()` builds an `ssdp:`-scheme URI from its argument."""
        uri = URI.ssdp("discover")
        assert str(uri) == "ssdp:discover"

    def test_upnp(self):
        """`URI.upnp()` builds an `upnp:`-scheme URI from its argument."""
        uri = URI.upnp("rootdevice")
        assert str(uri) == "upnp:rootdevice"

    def test_urn(self):
        """`URI.urn()` prefixes its argument with `urn:` to build a URN."""
        uri = URI.urn("schemas-upnp-org:device:MediaRenderer:1")
        assert str(uri) == "urn:schemas-upnp-org:device:MediaRenderer:1"

    def test_uuid(self):
        """`URI.uuid()` builds a `uuid:` URI from a `UUID` value."""
        value = UUID(int=1)
        uri = URI.uuid(value)
        assert str(uri) == f"uuid:{value}"
