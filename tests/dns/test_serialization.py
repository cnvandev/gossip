import struct
from datetime import timedelta
from ipaddress import IPv4Address

import pytest

from gossip.dns.constants import RecordClass, RecordType
from gossip.dns.model import DNSKey, Record
from gossip.dns.serialization import DNSDataReader

from .model import DummyQuestion, DummyRecord


def compression_pointer(offset: int) -> bytes:
    """The 2-byte RFC 1035 §4.1.4 compression pointer referencing `offset`."""
    return struct.pack("!H", 0xC000 | offset)


class TestRawReads:
    """Reading fixed-size chunks off the front of the buffer, and refusing
    to read past the end of it."""

    def test_read_bytes_advances_offset(self):
        """`read_bytes()` returns the requested slice and moves the cursor
        past it."""
        reader = DNSDataReader(b"\x01\x02\x03\x04")
        assert reader.read_bytes(2) == b"\x01\x02"
        assert reader.offset == 2

    def test_read_bytes_past_end_raises(self):
        """Asking for more bytes than remain raises rather than silently
        truncating."""
        reader = DNSDataReader(b"\x01\x02")
        with pytest.raises(IndexError):
            reader.read_bytes(5)

    def test_read_struct_unpacks_and_advances(self):
        """`read_struct()` unpacks a struct format and moves the cursor by
        its size."""
        reader = DNSDataReader(struct.pack("!HH", 42, 1))
        assert reader.read_struct("!HH") == (42, 1)
        assert reader.offset == 4

    def test_read_struct_past_end_raises(self):
        """A struct format that needs more bytes than remain raises rather
        than unpacking garbage."""
        reader = DNSDataReader(b"\x01")
        with pytest.raises(IndexError):
            reader.read_struct("!H")


class TestNameDecompression:
    """Reading wire-format domain names, including RFC 1035 §4.1.4
    compression pointers that reference bytes already seen elsewhere in the
    buffer."""

    def test_reads_uncompressed_name(self):
        """A plain length-prefixed name with no pointers reads back its
        wire bytes and advances past the terminating zero octet."""
        encoded = DNSKey._encode_domain("example.com")
        reader = DNSDataReader(encoded)
        assert reader.read_name_bytes() == encoded
        assert reader.offset == len(encoded)

    def test_reads_root_name(self):
        """The root name is a single zero octet."""
        reader = DNSDataReader(b"\x00")
        assert reader.read_name_bytes() == b"\x00"
        assert reader.offset == 1

    def test_pointer_to_start_of_prior_name_resolves_in_place(self):
        """A record referencing an earlier name entirely via a compression
        pointer decodes to that name, and the reader's cursor advances by
        just the 2-byte pointer, not the expanded name's length."""
        name = DNSKey._encode_domain("example.com")
        data = name + compression_pointer(0)
        reader = DNSDataReader(data)
        reader.offset = len(name)
        assert reader.read_name_bytes() == name
        assert reader.offset == len(name) + 2

    def test_pointer_into_middle_of_prior_name_resolves_suffix(self):
        """A pointer doesn't have to target the start of an earlier name -
        it can reference a suffix (e.g. pointing at "example.com" inside a
        previously-seen "www.example.com"), a common real-world compression
        pattern."""
        full_name = DNSKey._encode_domain("www.example.com")
        suffix_offset = 1 + len("www")  # skip past the "www" label
        data = full_name + compression_pointer(suffix_offset)
        reader = DNSDataReader(data)
        reader.offset = len(full_name)
        assert reader.read_name_bytes() == DNSKey._encode_domain("example.com")

    def test_pointer_cycle_raises(self):
        """Two pointers that reference each other would loop forever
        without a cycle guard."""
        data = compression_pointer(2) + compression_pointer(0)
        reader = DNSDataReader(data)
        with pytest.raises(IndexError):
            reader.read_name_bytes()

    def test_truncated_pointer_raises(self):
        """A pointer's leading byte (0xC0, the top two bits that mark a
        pointer per RFC 1035 §4.1.4) with no second byte to complete it is a
        malformed message, not a valid 0-length pointer."""
        reader = DNSDataReader(bytes([0xC0]))
        with pytest.raises(IndexError):
            reader.read_name_bytes()

    def test_label_exceeding_buffer_raises(self):
        """A label whose declared length runs past the end of the buffer is
        malformed input, not a short read."""
        reader = DNSDataReader(bytes([5]) + b"ab")
        with pytest.raises(IndexError):
            reader.read_name_bytes()


class TestQuestionReading:
    """Reading a Question section entry (NAME + TYPE + CLASS) off the wire."""

    def test_reads_name_type_and_class(self):
        """The parsed question's fields match what was written, and the
        cursor lands right after the fixed TYPE/CLASS fields."""
        data = bytes(DummyQuestion(domain="example.com", rtype=RecordType.A, rclass=RecordClass.IN))
        reader = DNSDataReader(data)
        question = reader.read_question()
        assert question.decode_name() == "example.com"
        assert question.rtype == RecordType.A
        assert question.rclass == RecordClass.IN
        assert reader.offset == len(data)


class TestRecordReading:
    """Reading a Resource Record (NAME + TYPE + CLASS + TTL + RDLENGTH +
    RDATA) off the wire, including RDATA that itself contains a compressed
    domain name."""

    def test_reads_opaque_rdata_verbatim(self):
        """A record type with no special RDATA handling (e.g. A) reads its
        RDATA bytes through unchanged."""
        data = bytes(Record.address("example.com", IPv4Address("1.2.3.4"), timedelta(seconds=300)))
        reader = DNSDataReader(data)
        record = reader.read_record()
        assert record.decode_ip() == IPv4Address("1.2.3.4")
        assert reader.offset == len(data)

    def test_expands_compressed_domain_rdata_for_ns(self):
        """An NS record's RDATA is itself a domain name, which may be
        compressed - it gets fully decompressed like any other name. Here
        it's a pointer back at the record's own owner name."""
        data = bytes(DummyRecord(rtype=RecordType.NS, rdata=compression_pointer(0)))
        reader = DNSDataReader(data)
        record = reader.read_record()
        assert record.decode_domain() == "example.com"
        assert reader.offset == len(data)

    def test_expands_compressed_domain_rdata_for_mx(self):
        """An MX record's RDATA is a 2-byte preference followed by a domain
        name, which is decompressed the same way as NS/CNAME/PTR targets."""
        rdata = struct.pack("!H", 10) + compression_pointer(0)
        data = bytes(DummyRecord(rtype=RecordType.MX, rdata=rdata))
        reader = DNSDataReader(data)
        record = reader.read_record()
        assert record.decode_mx() == (10, "example.com")
        assert reader.offset == len(data)

    def test_ttl_seconds_become_timedelta(self):
        """The wire TTL (seconds, big-endian uint32) is converted to a
        `timedelta`."""
        data = bytes(DummyRecord(ttl=timedelta(seconds=3600)))
        reader = DNSDataReader(data)
        record = reader.read_record()
        assert record.ttl.total_seconds() == 3600
