import struct
from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address

import pytest

from gossip.dns.constants import RecordClass, RecordType
from gossip.dns.model import DNSKey, Question, Record

from .model import DummyQuestion, DummyRecord

TTL = timedelta(seconds=300)


class TestDomainEncoding:
    """Converting a dotted domain string to and from RFC 1035 length-prefixed
    wire bytes."""

    def test_encode_simple_domain(self):
        """A two-label domain encodes as length-prefixed labels terminated
        by a zero byte."""
        assert DNSKey._encode_domain("example.com") == b"\x07example\x03com\x00"

    def test_encode_strips_trailing_dot(self):
        """A trailing dot (the fully-qualified form) doesn't add an extra
        empty label."""
        assert DNSKey._encode_domain("example.com.") == DNSKey._encode_domain("example.com")

    def test_encode_root_domain(self):
        """Both `.` and the empty string encode as the single root byte."""
        assert DNSKey._encode_domain(".") == b"\x00"
        assert DNSKey._encode_domain("") == b"\x00"

    def test_encode_label_too_long_raises(self):
        """A label over 63 octets is illegal on the wire and raises."""
        with pytest.raises(ValueError):
            DNSKey._encode_domain("a" * 64 + ".com")

    def test_decode_round_trips_encode(self):
        """Decoding the bytes produced by encoding a domain returns the
        original dotted string."""
        assert DummyQuestion(domain="example.com").decode_name() == "example.com"

    def test_decode_root_domain(self):
        """The root name decodes to `.`, whether stored as an empty byte
        string or the single zero-length-octet byte - the two wire forms a
        root name can take."""
        assert Question(rname=b"", rtype=RecordType.A, rclass=RecordClass.IN).decode_name() == "."
        assert Question(rname=b"\x00", rtype=RecordType.A, rclass=RecordClass.IN).decode_name() == "."


class TestDNSKeySerialization:
    """Serializing the common wire key prefix (NAME + TYPE + CLASS) shared
    by questions and records."""

    def test_bytes_is_name_type_class(self):
        """`bytes()` concatenates the encoded name with big-endian TYPE and
        CLASS values."""
        key = DummyQuestion()
        expected = DNSKey._encode_domain("example.com") + struct.pack("!HH", RecordType.A, RecordClass.IN)
        assert bytes(key) == expected


class TestQuestionFactory:
    """Building a `Question` from a domain name, type, and optional
    class."""

    def test_domain_defaults_to_class_in(self):
        """Omitting the class defaults to `RecordClass.IN`."""
        question = Question.domain("example.com", RecordType.A)
        assert question.rclass == RecordClass.IN

    def test_domain_encodes_the_name(self):
        """The constructed question's `rname` holds the wire-encoded form of
        the given domain, not the raw string."""
        question = Question.domain("example.com", RecordType.A)
        assert question.rname == DNSKey._encode_domain("example.com")


class TestRecordRdataDecoding:
    """Interpreting a `Record`'s opaque `rdata` bytes according to its
    `rtype`."""

    def test_decode_domain_for_ns_cname_ptr(self):
        """NS, CNAME, and PTR records carry a wire-encoded domain name as
        their rdata, which `decode_domain()` unpacks."""
        for rtype in (RecordType.NS, RecordType.CNAME, RecordType.PTR):
            record = Record.domain_target("example.com", rtype, "ns1.example.com", TTL)
            assert record.decode_domain() == "ns1.example.com"

    def test_decode_domain_returns_none_for_unrelated_type(self):
        """A record type that doesn't carry a domain name in its rdata
        returns `None` rather than misinterpreting arbitrary bytes."""
        assert DummyRecord(rtype=RecordType.TXT).decode_domain() is None

    def test_decode_mx_returns_preference_and_target(self):
        """An MX record's rdata is a 2-byte preference followed by a
        wire-encoded domain name."""
        record = Record.mx("example.com", 10, "mail.example.com", TTL)
        assert record.decode_mx() == (10, "mail.example.com")

    def test_decode_mx_returns_none_for_unrelated_type(self):
        """A non-MX record returns `None` from `decode_mx()`."""
        assert Record.address("example.com", IPv4Address("1.2.3.4"), TTL).decode_mx() is None

    def test_decode_ip_for_a_record(self):
        """An A record's 4-byte rdata decodes to an `IPv4Address`."""
        record = Record.address("example.com", IPv4Address("1.2.3.4"), TTL)
        assert record.decode_ip() == IPv4Address("1.2.3.4")

    def test_decode_ip_for_aaaa_record(self):
        """An AAAA record's 16-byte rdata decodes to an `IPv6Address`."""
        record = Record.address("example.com", IPv6Address("::1"), TTL)
        assert record.decode_ip() == IPv6Address("::1")

    def test_decode_ip_returns_none_for_malformed_rdata(self):
        """An A record whose rdata isn't exactly 4 bytes doesn't crash -
        it's treated as undecodable."""
        truncated = IPv4Address("1.2.3.4").packed[:3]
        record = DummyRecord(rtype=RecordType.A, rdata=truncated)
        assert record.decode_ip() is None

    def test_decode_ip_returns_none_for_unrelated_type(self):
        """A record type with no address rdata returns `None`."""
        assert DummyRecord(rtype=RecordType.TXT).decode_ip() is None


class TestRecordSerialization:
    """Serializing a `Record` to its full wire form: key prefix, TTL, RDLENGTH,
    and RDATA."""

    def test_bytes_appends_ttl_and_rdata(self):
        """`bytes()` extends the DNSKey prefix with a 4-byte TTL in seconds,
        a 2-byte rdata length, and the rdata itself."""
        rdata = IPv4Address("1.2.3.4").packed
        record = Record.address("example.com", IPv4Address("1.2.3.4"), timedelta(seconds=300))
        expected = (
            DNSKey._encode_domain("example.com")
            + struct.pack("!HH", RecordType.A, RecordClass.IN)
            + struct.pack("!IH", 300, len(rdata))
            + rdata
        )
        assert bytes(record) == expected


class TestRecordFactories:
    """Convenience constructors for common record shapes: addresses,
    domain targets, MX, deletion, insertion, and TSIG signing."""

    def test_address_picks_type_from_ip_version(self):
        """`address()` builds an A record for an IPv4 address and an AAAA
        record for IPv6, with the IP packed into rdata."""
        a_record = Record.address("example.com", IPv4Address("1.2.3.4"), TTL)
        assert a_record.rtype == RecordType.A
        assert a_record.decode_ip() == IPv4Address("1.2.3.4")

        aaaa_record = Record.address("example.com", IPv6Address("::1"), TTL)
        assert aaaa_record.rtype == RecordType.AAAA
        assert aaaa_record.decode_ip() == IPv6Address("::1")

    def test_domain_target_encodes_target_as_rdata(self):
        """`domain_target()` builds a record whose rdata is the wire-encoded
        target domain, for the given record type."""
        record = Record.domain_target("example.com", RecordType.NS, "ns1.example.com", TTL)
        assert record.rtype == RecordType.NS
        assert record.decode_domain() == "ns1.example.com"

    def test_mx_encodes_preference_and_target(self):
        """`mx()` builds an MX record whose rdata is the 2-byte preference
        followed by the wire-encoded target domain."""
        record = Record.mx("example.com", 10, "mail.example.com", TTL)
        assert record.decode_mx() == (10, "mail.example.com")

    def test_address_domain_target_and_mx_use_the_given_ttl(self):
        """None of the three factories assume a default TTL - DNS doesn't
        specify one, so it's always the caller's given value."""
        custom_ttl = timedelta(seconds=42)
        for record in (
            Record.address("example.com", IPv4Address("1.2.3.4"), custom_ttl),
            Record.domain_target("example.com", RecordType.NS, "ns1.example.com", custom_ttl),
            Record.mx("example.com", 10, "mail.example.com", custom_ttl),
        ):
            assert record.ttl == custom_ttl

    def test_address_domain_target_and_mx_default_to_class_in(self):
        """Unless overridden, all three factories default to CLASS IN."""
        for record in (
            Record.address("example.com", IPv4Address("1.2.3.4"), TTL),
            Record.domain_target("example.com", RecordType.NS, "ns1.example.com", TTL),
            Record.mx("example.com", 10, "mail.example.com", TTL),
        ):
            assert record.rclass == RecordClass.IN

    def test_delete_has_zero_ttl_and_class_any(self):
        """A delete record has an empty rdata, zero TTL, and CLASS ANY, per
        the RFC 2136 update convention."""
        record = Record.delete("example.com", RecordType.A)
        assert record.rclass == RecordClass.ANY
        assert record.ttl == timedelta(seconds=0)
        assert record.rdata == b""
        assert record.rname == DNSKey._encode_domain("example.com")

    def test_insert_defaults_to_class_in(self):
        """Omitting the class defaults an insert record to CLASS IN."""
        rdata = IPv4Address("1.2.3.4").packed
        record = Record.insert("example.com", RecordType.A, timedelta(seconds=60), rdata)
        assert record.rclass == RecordClass.IN
        assert record.ttl == timedelta(seconds=60)
        assert record.rdata == rdata

    def test_insert_respects_a_given_class(self):
        """A class other than IN is honored, not silently overridden -
        `insert()` used to hardcode CLASS IN regardless of what was passed."""
        record = Record.insert("example.com", RecordType.A, timedelta(seconds=60), b"data", rclass=RecordClass.CH)
        assert record.rclass == RecordClass.CH

    def test_tsig_uses_the_encoded_domain_verbatim(self):
        """Unlike the other factories, `tsig()` doesn't re-encode its name
        argument - it's already wire-encoded since it comes from the TSIG
        key name, not a plain domain string."""
        encoded_key_name = DNSKey._encode_domain("key.example.com")
        record = Record.tsig(encoded_key_name, b"signature-bytes")
        assert record.rname == encoded_key_name
        assert record.rtype == RecordType.TSIG
        assert record.rclass == RecordClass.ANY
        assert record.rdata == b"signature-bytes"


class TestQuestionRepr:
    """`repr()` formatting for a bare question, with no rdata to interpret."""

    def test_repr_shows_type_and_decoded_name(self):
        """A question's repr names its record type and decoded domain."""
        assert repr(DummyQuestion()) == "A: example.com"


class TestRecordRepr:
    """`repr()` formatting, which resolves record-type-specific rdata into a
    human-readable value rather than showing raw bytes."""

    def test_repr_shows_decoded_ip_for_address_records(self):
        """A/AAAA records show their decoded IP address."""
        record = Record.address("example.com", IPv4Address("1.2.3.4"), TTL)
        assert "1.2.3.4" in repr(record)

    def test_repr_shows_decoded_domain_for_ns_records(self):
        """NS records show their decoded target domain."""
        record = Record.domain_target("example.com", RecordType.NS, "ns1.example.com", TTL)
        assert "ns1.example.com" in repr(record)

    def test_repr_shows_decoded_mx_tuple(self):
        """MX records show their decoded (preference, target) tuple."""
        record = Record.mx("example.com", 10, "mail.example.com", TTL)
        assert "mail.example.com" in repr(record) and "10" in repr(record)

    def test_repr_falls_back_to_raw_rdata_for_other_types(self):
        """A type with no dedicated decoder shows the raw rdata bytes."""
        record = DummyRecord(rtype=RecordType.TXT, rdata=b"opaque-payload")
        assert repr(record.rdata) in repr(record)
