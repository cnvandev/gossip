import struct
from datetime import timedelta

from gossip.dns.constants import RecordClass, RecordType
from gossip.dns.model import Question, Record


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
