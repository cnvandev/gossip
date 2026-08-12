from ipaddress import IPv4Address, IPv6Address

import pytest

from gossip.network.endpoint import Endpoint


class TestEndpointConstruction:
    """Building an `Endpoint` from a raw socket address tuple."""

    def test_for_addr_with_ipv4(self):
        """Building from a `(host, port)` tuple parses an IPv4 host into a
        real `IPv4Address`."""
        endpoint = Endpoint.for_addr(("127.0.0.1", 80))
        assert endpoint == Endpoint(IPv4Address("127.0.0.1"), 80)

    def test_for_addr_with_ipv6(self):
        """Building from a `(host, port)` tuple parses an IPv6 host into a
        real `IPv6Address`."""
        endpoint = Endpoint.for_addr(("::1", 1900))
        assert endpoint == Endpoint(IPv6Address("::1"), 1900)

    def test_for_addr_with_ipv6_four_tuple(self):
        """Building from the 4-tuple `(host, port, flowinfo, scope_id)`
        form used for IPv6 sockets only looks at the first two
        elements."""
        endpoint = Endpoint.for_addr(("::1", 1900, 0, 0))
        assert endpoint == Endpoint(IPv6Address("::1"), 1900)


class TestEndpointStringForm:
    """Converting an `Endpoint` to and from its string form, for both
    address families."""

    def test_str_with_ipv4(self):
        """An IPv4 endpoint renders as plain `address:port`."""
        endpoint = Endpoint(IPv4Address("192.168.1.1"), 1900)
        assert str(endpoint) == "192.168.1.1:1900"

    def test_str_with_ipv6_is_bracketed(self):
        """An IPv6 endpoint renders with the address in brackets,
        `[address]:port` - without them, the address's own colons would be
        indistinguishable from the one separating it from the port."""
        endpoint = Endpoint(IPv6Address("::1"), 1900)
        assert str(endpoint) == "[::1]:1900"

    def test_parse_ipv4(self):
        """Parsing an `address:port` string produces an `Endpoint` with
        those exact address and port fields."""
        endpoint = Endpoint.parse("239.255.255.250:1900")
        assert endpoint == Endpoint(IPv4Address("239.255.255.250"), 1900)

    def test_parse_bracketed_ipv6(self):
        """Parsing a bracketed `[address]:port` string produces an
        `Endpoint` with an `IPv6Address`."""
        endpoint = Endpoint.parse("[2001:db8::239:1900]:1900")
        assert endpoint == Endpoint(IPv6Address("2001:db8::239:1900"), 1900)

    def test_parse_round_trips_with_str_ipv4(self):
        """Parsing the string form of an IPv4 `Endpoint` reproduces that
        same `Endpoint`."""
        endpoint = Endpoint(IPv4Address("10.0.0.5"), 8080)
        assert Endpoint.parse(str(endpoint)) == endpoint

    def test_parse_round_trips_with_str_ipv6(self):
        """Parsing the string form of an IPv6 `Endpoint` reproduces that
        same `Endpoint`."""
        endpoint = Endpoint(IPv6Address("fe80::1"), 8080)
        assert Endpoint.parse(str(endpoint)) == endpoint

    def test_parse_round_trips_ipv4_mapped_ipv6_address(self):
        """An IPv4-mapped IPv6 address (RFC 4291 §2.5.5.2, `::ffff:a.b.c.d`)
        round-trips correctly even though its text form mixes dots and
        colons - the bracket parsing only looks for the literal `]:` that
        closes the address, so the dotted-quad portion inside doesn't
        confuse it the way it would a naive colon-split."""
        endpoint = Endpoint(IPv6Address("::ffff:192.0.2.1"), 1900)
        assert str(endpoint) == "[::ffff:192.0.2.1]:1900"
        assert Endpoint.parse(str(endpoint)) == endpoint

    def test_parse_round_trips_unspecified_ipv6_address(self):
        """The degenerate all-zeros IPv6 address `::` round-trips too - the
        shortest possible bracketed address, with nothing between `[` and
        `]:` but the two characters of `::` itself."""
        endpoint = Endpoint(IPv6Address("::"), 1900)
        assert str(endpoint) == "[::]:1900"
        assert Endpoint.parse(str(endpoint)) == endpoint

    def test_parse_rejects_ipv6_without_brackets(self):
        """An IPv6 host without brackets fails to parse, rather than being
        misread as a shorter address with a garbled port - there's no way
        to tell where the address ends and the port begins without
        brackets."""
        with pytest.raises(ValueError):
            Endpoint.parse("::1:80")

    def test_parse_rejects_unclosed_bracket(self):
        """A `[` with no matching `]:` fails to parse, instead of silently
        treating the rest of the string as the address with no port."""
        with pytest.raises(ValueError):
            Endpoint.parse("[::1")

    def test_parse_rejects_bracketed_address_with_no_port(self):
        """A bracketed address with nothing after it fails to parse,
        rather than raising a confusing error from an empty port
        string."""
        with pytest.raises(ValueError):
            Endpoint.parse("[::1]")


class TestEndpointEquality:
    """Whether two `Endpoint`s are interchangeable, as a plain `NamedTuple`
    should be."""

    def test_equality_and_hashing_as_namedtuple(self):
        """Two `Endpoint`s built from the same address and port are equal,
        hash the same, and collapse to a single entry in a set."""
        a = Endpoint(IPv4Address("10.0.0.1"), 80)
        b = Endpoint(IPv4Address("10.0.0.1"), 80)
        assert a == b
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_ipv4_and_ipv6_endpoints_on_the_same_port_are_not_equal(self):
        """An IPv4 and an IPv6 `Endpoint` are different, even if they
        happen to share a port - equality isn't based on the port
        alone."""
        a = Endpoint(IPv4Address("127.0.0.1"), 80)
        b = Endpoint(IPv6Address("::1"), 80)
        assert a != b
