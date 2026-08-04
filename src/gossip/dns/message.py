import hmac
import logging
import secrets
import struct
import time
from asyncio.streams import StreamReader
from dataclasses import dataclass, field
from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address
from typing import Self, SupportsBytes

from gossip.dns.constants import TSIG_ALGORITHMS, RecordClass, RecordType
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable

log = logging.getLogger(__name__)


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
                return f"{self.rtype.name}: {self.decode_name()} -> {self.decode_ip()}"
            case RecordType.NS:
                return f"{self.rtype.name}: {self.decode_name()} -> {self.decode_domain()}"
            case RecordType.MX:
                return f"{self.rtype.name}: {self.decode_name()} -> {self.decode_mx()}"
            case _:
                return f"{self.rtype.name}: {self.decode_name()} -> {self.rdata}"

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

class DNSDataReader:
    """Zero-allocation style binary reader tracking offset & label compression."""

    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.label_map: dict[int, bytes] = {}

    def read_bytes(self, n: int) -> bytes:
        if self.offset + n > len(self.data):
            raise IndexError("Buffer underflow while reading raw bytes")
        res = self.data[self.offset : self.offset + n]
        self.offset += n
        return res

    def read_struct(self, fmt: str) -> tuple:
        size = struct.calcsize(fmt)
        if self.offset + size > len(self.data):
            raise IndexError("Buffer underflow while unpacking struct")
        res = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += size
        return res

    def read_name_bytes(self) -> bytes:
        """Reads wire-format domain name, fully resolving compression pointers."""
        initial_offset = self.offset
        visited_offsets = []

        raw_bytes, bytes_consumed = self._read_name_at(initial_offset, visited_offsets)
        self.offset += bytes_consumed
        return raw_bytes

    def _read_name_at(self, offset: int, visited: list[int]) -> tuple[bytes, int]:
        if offset in self.label_map:
            return self.label_map[offset], 2 if (self.data[offset] & 0xC0) == 0xC0 else len(self.label_map[offset])

        if offset in visited:
            raise IndexError("Compression pointer cycle detected")
        visited.append(offset)

        b = self.data[offset]
        if b == 0:
            return b"\x00", 1

        if (b & 0xC0) == 0xC0:
            if offset + 2 > len(self.data):
                raise IndexError("Pointer truncated")
            ptr = struct.unpack_from("!H", self.data, offset)[0] & 0x3FFF
            target_bytes, _ = self._read_name_at(ptr, visited)
            self.label_map[offset] = target_bytes
            return target_bytes, 2

        length = b
        end = offset + 1 + length
        if end > len(self.data):
            raise IndexError("Label exceeds buffer length")

        rest_bytes, rest_consumed = self._read_name_at(end, visited)
        full_bytes = self.data[offset : end] + rest_bytes
        self.label_map[offset] = full_bytes
        return full_bytes, 1 + length + rest_consumed

    def read_question(self) -> Question:
        """Reads a single Question entry from the stream."""
        rname = self.read_name_bytes()
        rtype_val, rclass_val = self.read_struct("!HH")
        return Question(
            rname=rname,
            rtype=RecordType(rtype_val),
            rclass=RecordClass(rclass_val),
        )

    def read_record(self) -> Record:
        """Reads a single Resource Record entry, expanding compressed domain fields."""
        rname = self.read_name_bytes()
        rtype_val, rclass_val, ttl_seconds, rdlength = self.read_struct("!HHIH")
        rtype = RecordType(rtype_val)

        if rtype in (RecordType.NS, RecordType.CNAME, RecordType.PTR):
            rdata = self.read_name_bytes()
        elif rtype == RecordType.MX:
            pref_bytes = self.read_bytes(2)
            rdata = pref_bytes + self.read_name_bytes()
        else:
            rdata = self.read_bytes(rdlength)

        return Record(
            rname=rname,
            rtype=rtype,
            rclass=RecordClass(rclass_val),
            ttl=timedelta(seconds=ttl_seconds),
            rdata=rdata,
        )


@dataclass
class DNSMessage(Serializable):

    is_response: bool = False
    is_truncated: bool = False
    is_recursive: bool = False
    questions: list[Question] = field(default_factory=list)
    answers: list[Record] = field(default_factory=list)
    authorities: list[Record] = field(default_factory=list)
    additional: list[Record] = field(default_factory=list)
    transaction_id: int = field(default_factory=lambda: secrets.randbelow(2**16))

    def sign_tsig(self, name: str, secret: bytes, algorithm: str = "hmac-sha256.", fudge: int = 300) -> None:
        """Computes and appends an RFC 2845 TSIG record to the additional section."""
        # Capture current time as 48-bit uint (6 bytes)
        now = int(time.time())
        time_bytes = now.to_bytes(6, byteorder="big")
        encoded_name = DNSKey._encode_domain(name)
        encoded_algo = DNSKey._encode_domain(algorithm)

        # Build the TSIG pseudo-header buffer for HMAC calculation
        tsig_variables = (
            encoded_name +
            struct.pack("!IH", 0x00FF, 0) +  # Class ANY (255), TTL (0)
            encoded_algo +
            time_bytes + # 48-bit timestamp
            struct.pack("!HHH", fudge, 0, 0)  # Fudge (300), Error (0), Other Len (0)
        )
        data_to_sign = bytes(self) + tsig_variables

        # 4. Generate HMAC-SHA256 signature
        signer = TSIG_ALGORITHMS[algorithm]
        mac = hmac.new(secret, data_to_sign, signer).digest()

        # 5. Build TSIG RDATA payload
        signature = (
            encoded_algo +
            time_bytes +
            struct.pack("!HH", fudge, len(mac)) +
            mac +
            struct.pack("!HHH", self.transaction_id, 0, 0)  # Orig ID, Error, Other Len
        )

        # 6. Append TSIG record to the additional section
        self.additional.append(Record.tsig(encoded_name, signature))

    def __bytes__(self) -> bytes:
        flags = 0
        if self.is_response:
            flags |= 0x8000
        if self.is_truncated:
            flags |= 0x0200
        if self.is_recursive:
            flags |= 0x0100

        header = struct.pack(
            "!HHHHHH",
            self.transaction_id,
            flags,
            len(self.questions),
            len(self.answers),
            len(self.authorities),
            len(self.additional),
        )

        body = bytearray()
        for q in self.questions:
            body.extend(bytes(q))
        for rr in self.answers:
            body.extend(bytes(rr))
        for rr in self.authorities:
            body.extend(bytes(rr))
        for rr in self.additional:
            body.extend(bytes(rr))

        return bytes(header + body)

    @classmethod
    def query(
        cls,
        domain: str,
        rtype: RecordType = RecordType.A,
        rclass: RecordClass = RecordClass.IN,
        recursive: bool = False,
    ) -> Self:
        """Constructs an outgoing DNS query message for a domain."""
        return cls(
            is_recursive=recursive,
            questions=[Question.domain(domain, rtype, rclass)],
        )

    @classmethod
    def update(
        cls,
        zone: str,
        hostname: str,
        ip_address: IPv4Address,
        ttl: timedelta | int,
        rtype: RecordType,
        rclass: RecordClass = RecordClass.IN,
    ) -> Self:
        """Constructs an RFC 2136 Dynamic DNS Update message."""
        if isinstance(ttl, int):
            ttl = timedelta(seconds=ttl)

        return cls(
            questions=[Question.domain(zone, RecordType.SOA, rclass)],
            authorities=[
                Record.delete(hostname, rtype),
                Record.insert(hostname, rtype, rclass, ttl, ip_address.packed),
            ],
        )

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None:
        if isinstance(reader, StreamReader):
            data = await reader.read()
        else:
            data, _ = reader

        buf = DNSDataReader(data)
        try:
            transaction_id, flags, qdcount, ancount, nscount, arcount = buf.read_struct("!HHHHHH")

            questions = [buf.read_question() for _ in range(qdcount)]
            answers = [buf.read_record() for _ in range(ancount)]
            authorities = [buf.read_record() for _ in range(nscount)]
            additional = [buf.read_record() for _ in range(arcount)]

            return cls(
                transaction_id=transaction_id,
                is_response=bool(flags & 0x8000),
                is_truncated=bool(flags & 0x0200),
                is_recursive=bool(flags & 0x0100),
                questions=questions,
                answers=answers,
                authorities=authorities,
                additional=additional,
            )

        except (IndexError, struct.error, ValueError):
            return None
