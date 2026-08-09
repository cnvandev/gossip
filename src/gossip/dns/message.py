import hmac
import logging
import secrets
import struct
import time
from asyncio.streams import StreamReader
from dataclasses import dataclass, field
from datetime import timedelta
from ipaddress import IPv4Address
from typing import Self

from gossip.dns.constants import TSIG_ALGORITHMS, OpCode, RecordClass, RecordType, ResponseCode
from gossip.dns.model import DNSKey, Question, Record
from gossip.dns.serialization import DNSDataReader
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable

log = logging.getLogger(__name__)


@dataclass
class DNSMessage(Serializable):
    """A DNS message."""

    is_response: bool = False
    is_authoritative: bool = False
    is_truncated: bool = False
    is_recursive: bool = False
    recursion_available: bool = False
    is_authentic: bool = False
    checking_disabled: bool = False
    response_code: ResponseCode = ResponseCode.NO_ERROR
    operation_code: OpCode = OpCode.QUERY
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

        # Generate the appropriate signature & append it
        signer = TSIG_ALGORITHMS[algorithm]
        mac = hmac.new(secret, data_to_sign, signer).digest()
        signature = (
            encoded_algo +
            time_bytes +
            struct.pack("!HH", fudge, len(mac)) +
            mac +
            struct.pack("!HHH", self.transaction_id, 0, 0)  # Orig ID, Error, Other Len
        )
        self.additional.append(Record.tsig(encoded_name, signature))

    def __repr__(self) -> str:
        if not self.is_response:
            flags = ", recursive" if self.is_recursive else ""
            return f"{self.operation_code.name}({self.questions[0]}{flags})"
        else:
            sections = {}
            if self.answers:
                sections["answers"] = self.answers
            if self.authorities:
                sections["authorities"] = self.authorities
            if self.additional:
                sections["additional"] = self.additional
            flags = []
            if self.is_authoritative:
                flags.append("authoritative")
            if self.is_truncated:
                flags.append("truncated")
            if self.is_authentic:
                flags.append("authentic")
            flag_string = ": " if flags else "" + ", ".join(flags) + (" " if flags else "")

            return f"RESPONSE({self.response_code.name}{flag_string}{", ".join(f"{name}={s}" for name, s in sections.items())})"

    def __bytes__(self) -> bytes:
        flags = 0
        if self.is_response:
            flags |= 0x8000
        if self.is_authoritative:
            flags |= 0x0400
        if self.is_truncated:
            flags |= 0x0200
        if self.is_recursive:
            flags |= 0x0100
        if self.recursion_available:
            flags |= 0x0080
        if self.is_authentic:
            flags |= 0x0020
        if self.checking_disabled:
            flags |= 0x0010
        flags |= self.response_code.value
        flags |= self.operation_code << 11

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
            operation_code=OpCode.QUERY,
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
            operation_code=OpCode.UPDATE,
            questions=[Question.domain(zone, RecordType.SOA, rclass)],
            authorities=[
                Record.delete(hostname, rtype),
                Record.insert(hostname, rtype, rclass, ttl, ip_address.packed),
            ],
        )

    @classmethod
    def insert(
        cls,
        zone: str,
        hostname: str,
        ip_address: IPv4Address,
        ttl: timedelta | int,
        rtype: RecordType,
        rclass: RecordClass = RecordClass.IN,
    ) -> Self:
        """Constructs an RFC 2136 Dynamic DNS Insert message."""
        if isinstance(ttl, int):
            ttl = timedelta(seconds=ttl)

        return cls(
            operation_code=OpCode.UPDATE,
            questions=[Question.domain(zone, RecordType.SOA, rclass)],
            authorities=[
                Record.insert(hostname, rtype, rclass, ttl, ip_address.packed),
            ],
        )

    @classmethod
    def delete(
        cls,
        zone: str,
        hostname: str,
        rtype: RecordType,
        rclass: RecordClass = RecordClass.IN,
    ) -> Self:
        """Constructs an RFC 2136 Dynamic DNS Delete message."""
        return cls(
            operation_code=OpCode.UPDATE,
            questions=[Question.domain(zone, RecordType.SOA, rclass)],
            authorities=[
                Record.delete(hostname, rtype),
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
                is_authoritative=bool(flags & 0x0400),
                is_truncated=bool(flags & 0x0200),
                is_recursive=bool(flags & 0x0100),
                recursion_available=bool(flags & 0x0080),
                is_authentic=bool(flags & 0x0020),
                checking_disabled=bool(flags & 0x0010),
                response_code=ResponseCode(flags & 0x000F),
                operation_code=OpCode((flags >> 11) & 0x0F),
                questions=questions,
                answers=answers,
                authorities=authorities,
                additional=additional,
            )

        except (IndexError, struct.error, ValueError):
            return None
