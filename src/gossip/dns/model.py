import struct
from dataclasses import dataclass
from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address
from typing import Self, SupportsBytes

from gossip.dns.constants import RecordClass, RecordType


@dataclass(frozen=True)
class DNSKey(SupportsBytes):
    """Base wire key tuple (name, type, class) present across DNS sections."""

    rname: bytes
    rtype: RecordType
    rclass: RecordClass

    def _parse_wire_domain(self, wire_bytes: bytes) -> str:
        """Helper to convert raw length-prefixed bytes to dotted domain string."""
        if not wire_bytes or wire_bytes == b"\x00":
            return "."

        labels = []
        offset = 0
        total_len = len(wire_bytes)

        while offset < total_len:
            length = wire_bytes[offset]
            if length == 0:
                break
            offset += 1
            labels.append(wire_bytes[offset : offset + length].decode("ascii"))
            offset += length

        return ".".join(labels)

    def decode_name(self) -> str:
        """Decodes entry owner name to a dotted domain string."""
        return self._parse_wire_domain(self.rname)

    def __repr__(self) -> str:
        return f"{self.rtype.name}: {self.decode_name()}"

    def __bytes__(self) -> bytes:
        """Serializes the common wire key prefix (NAME + TYPE + CLASS)."""
        return self.rname + struct.pack("!HH", self.rtype, self.rclass)

    @staticmethod
    def _encode_domain(domain: str) -> bytes:
        """Converts a dotted domain string (e.g., 'example.com') to RFC 1035 wire bytes."""
        if not domain or domain == ".":
            return b"\x00"

        out = bytearray()
        for label in domain.strip(".").split("."):
            encoded_label = label.encode("ascii")
            if len(encoded_label) > 63:
                raise ValueError(f"Label too long: {label}")
            out.append(len(encoded_label))
            out.extend(encoded_label)
        out.append(0)
        return bytes(out)


@dataclass(frozen=True)
class Question(DNSKey):
    """Question section entry.

    It's just a DNS tuple (name, type, and class).
    """

    def __repr__(self) -> str:
        return f"{self.rtype.name}: {self.decode_name()}"

    @classmethod
    def domain(cls, domain: str, rtype: RecordType, rclass: RecordClass = RecordClass.IN) -> Self:
        return cls(
            rname=cls._encode_domain(domain),
            rtype=rtype,
            rclass=rclass,
        )


@dataclass(frozen=True)
class Record(DNSKey):
    """Resource Record section entry extending DNSKey with TTL and RDATA."""

    ttl: timedelta
    rdata: bytes

    def decode_domain(self) -> str | None:
        """Decodes target domain for NS, CNAME, or PTR records."""
        if self.rtype in (RecordType.NS, RecordType.CNAME, RecordType.PTR):
            return self._parse_wire_domain(self.rdata)
        return None

    def decode_mx(self) -> tuple[int, str] | None:
        """Decodes MX record into (preference, target_domain)."""
        if self.rtype == RecordType.MX and len(self.rdata) >= 2:
            preference = struct.unpack("!H", self.rdata[:2])[0]
            domain = self._parse_wire_domain(self.rdata[2:])
            return preference, domain
        return None

    def decode_ip(self) -> IPv4Address | IPv6Address | None:
        """Parses A or AAAA rdata into ipaddress objects."""
        if self.rtype == RecordType.A and len(self.rdata) == 4:
            return IPv4Address(self.rdata)
        elif self.rtype == RecordType.AAAA and len(self.rdata) == 16:
            return IPv6Address(self.rdata)
        return None

    def __repr__(self) -> str:
        match self.rtype:
            case RecordType.A | RecordType.AAAA:
                value = self.decode_ip()
            case RecordType.NS:
                value = self.decode_domain()
            case RecordType.MX:
                value = self.decode_mx()
            case _:
                value = self.rdata
        return f"{super().__repr__()} -> {value}"

    def __bytes__(self) -> bytes:
        """Serializes the full Resource Record (Key prefix + TTL + RDATA)."""
        ttl_seconds = int(self.ttl.total_seconds())
        return super().__bytes__() + struct.pack("!IH", ttl_seconds, len(self.rdata)) + self.rdata

    @classmethod
    def delete(cls, hostname: str, rtype: RecordType) -> Self:
        """Delete old records (CLASS = ANY, TYPE = A, TTL = 0, RDLEN = 0)."""
        return cls(
            rname=cls._encode_domain(hostname),
            rtype=rtype,
            rclass=RecordClass.ANY,
            ttl=timedelta(seconds=0),
            rdata=b"",
        )

    @classmethod
    def insert(cls, hostname: str, rtype: RecordType, rclass: RecordClass, ttl: timedelta, rdata: bytes) -> Self:
        """Insert a new record with the given hostname, type, and data."""
        return cls(
            rname=cls._encode_domain(hostname),
            rtype=rtype,
            rclass=RecordClass.IN,
            ttl=ttl,
            rdata=rdata,
        )

    @classmethod
    def tsig(cls, encoded_domain: bytes, rdata: bytes) -> Self:
        """Create a TSIG record for signing a message.

        Unlike the other factories, this doesn't encode the domain name
        since it's already encoded in the TSIG key name.
        """
        return cls(
            rname=encoded_domain,
            rtype=RecordType.TSIG,
            rclass=RecordClass.ANY,  # Class ANY
            ttl=timedelta(seconds=0),
            rdata=rdata,
        )
