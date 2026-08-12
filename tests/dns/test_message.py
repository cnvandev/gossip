import hashlib
import hmac
import struct
from asyncio import StreamReader
from asyncio import run as run_async
from datetime import timedelta
from ipaddress import IPv4Address
from unittest.mock import patch

from gossip.dns.constants import OpCode, RecordClass, RecordType, ResponseCode
from gossip.dns.message import DNSMessage
from gossip.dns.model import DNSKey, Question, Record
from gossip.network.endpoint import Endpoint

ENDPOINT = Endpoint(IPv4Address("127.0.0.1"), 53)


class TestDNSMessageWireSerialization:
    """Serializing a `DNSMessage` to its RFC 1035 §4.1.1 wire header plus
    concatenated section bodies."""

    def test_header_carries_transaction_id_and_section_counts(self):
        """The 12-byte header leads with the transaction ID, then a count
        for each of the four sections, matching their list lengths."""
        message = DNSMessage(
            transaction_id=0x1234,
            questions=[Question.domain("example.com", RecordType.A)],
            answers=[Record.address("example.com", IPv4Address("1.2.3.4"), timedelta(seconds=300))],
        )
        tid, _, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", bytes(message)[:12])
        assert tid == 0x1234
        assert (qdcount, ancount, nscount, arcount) == (1, 1, 0, 0)

    def test_flag_bits_and_codes_pack_into_the_second_header_word(self):
        """Every boolean flag sets its own bit, and the response/operation
        codes pack into the low nibble and bits 11-14 respectively."""
        message = DNSMessage(
            is_response=True,
            is_authoritative=True,
            is_truncated=True,
            is_recursive=True,
            recursion_available=True,
            is_authentic=True,
            checking_disabled=True,
            response_code=ResponseCode.NAME_ERROR,
            operation_code=OpCode.UPDATE,
        )
        _, flags, *_ = struct.unpack("!HHHHHH", bytes(message)[:12])
        expected = 0x8000 | 0x0400 | 0x0200 | 0x0100 | 0x0080 | 0x0020 | 0x0010 | ResponseCode.NAME_ERROR | (OpCode.UPDATE << 11)
        assert flags == expected

    def test_body_concatenates_sections_in_order(self):
        """The body is questions, then answers, then authorities, then
        additional - each record serialized via its own `bytes()`."""
        question = Question.domain("example.com", RecordType.A)
        answer = Record.address("example.com", IPv4Address("1.2.3.4"), timedelta(seconds=300))
        authority = Record.domain_target("example.com", RecordType.NS, "ns1.example.com", timedelta(seconds=300))
        additional = Record.tsig(DNSKey._encode_domain("key.example.com"), b"signature")
        message = DNSMessage(
            transaction_id=0,
            questions=[question],
            answers=[answer],
            authorities=[authority],
            additional=[additional],
        )
        expected_body = bytes(question) + bytes(answer) + bytes(authority) + bytes(additional)
        assert bytes(message)[12:] == expected_body


class TestDNSMessageFactories:
    """Building outgoing messages: plain queries and RFC 2136 Dynamic
    Update variants."""

    def test_query_is_a_single_question_message(self):
        """`query()` builds a non-response QUERY message with exactly the
        requested question."""
        message = DNSMessage.query("example.com", RecordType.A)
        assert message.operation_code == OpCode.QUERY
        assert not message.is_response
        assert message.questions == [Question.domain("example.com", RecordType.A)]

    def test_query_recursive_flag(self):
        """Passing `recursive=True` sets the recursion-desired flag."""
        assert DNSMessage.query("example.com", recursive=True).is_recursive
        assert not DNSMessage.query("example.com").is_recursive

    def test_update_deletes_then_inserts(self):
        """`update()` is an RFC 2136 update whose authority section deletes
        the old record before inserting the new one, in that order."""
        message = DNSMessage.update("zone.example.com", "host.example.com", IPv4Address("1.2.3.4"), 300, RecordType.A)
        assert message.operation_code == OpCode.UPDATE
        assert message.questions == [Question.domain("zone.example.com", RecordType.SOA, RecordClass.IN)]
        delete_rr, insert_rr = message.authorities
        assert delete_rr == Record.delete("host.example.com", RecordType.A)
        assert insert_rr.decode_ip() == IPv4Address("1.2.3.4")
        assert insert_rr.ttl == timedelta(seconds=300)

    def test_update_accepts_an_integer_ttl(self):
        """An integer TTL is treated as a number of seconds."""
        message = DNSMessage.update("zone.example.com", "host.example.com", IPv4Address("1.2.3.4"), 60, RecordType.A)
        assert message.authorities[1].ttl == timedelta(seconds=60)

    def test_insert_only_inserts(self):
        """`insert()` is an update with just the insertion, no delete."""
        message = DNSMessage.insert("zone.example.com", "host.example.com", IPv4Address("1.2.3.4"), 300, RecordType.A)
        assert len(message.authorities) == 1
        assert message.authorities[0].decode_ip() == IPv4Address("1.2.3.4")

    def test_delete_only_deletes(self):
        """`delete()` is an update with just the deletion, no insert."""
        message = DNSMessage.delete("zone.example.com", "host.example.com", RecordType.A)
        assert message.authorities == [Record.delete("host.example.com", RecordType.A)]


class TestDNSMessageReadFrom:
    """Parsing a `DNSMessage` back from its wire bytes, given as a
    `(bytes, Endpoint)` pair rather than a live stream."""

    def test_round_trips_a_serialized_message(self):
        """A message serialized with `bytes()` parses back into an
        equivalent message via `read_from()`."""
        original = DNSMessage.query("example.com", RecordType.A)
        original.answers.append(Record.address("example.com", IPv4Address("1.2.3.4"), timedelta(seconds=300)))

        parsed = run_async(DNSMessage.read_from((bytes(original), ENDPOINT)))

        assert parsed is not None
        assert parsed.transaction_id == original.transaction_id
        assert parsed.questions == original.questions
        assert parsed.answers == original.answers

    def test_reads_from_a_live_stream_reader_too(self):
        """The other accepted input, a real `asyncio.StreamReader`, is read
        to EOF and parsed the same way as the `(bytes, Endpoint)` form."""

        async def read_it() -> DNSMessage | None:
            original = DNSMessage.query("example.com", RecordType.A)
            reader = StreamReader()
            reader.feed_data(bytes(original))
            reader.feed_eof()
            return await DNSMessage.read_from(reader)

        parsed = run_async(read_it())
        assert parsed is not None
        assert parsed.questions == [Question.domain("example.com", RecordType.A)]

    def test_flags_and_codes_round_trip(self):
        """Every boolean flag and both codes survive a serialize/parse
        round trip."""
        original = DNSMessage(
            is_response=True,
            is_authoritative=True,
            is_truncated=True,
            is_recursive=True,
            recursion_available=True,
            is_authentic=True,
            checking_disabled=True,
            response_code=ResponseCode.NAME_ERROR,
            operation_code=OpCode.UPDATE,
        )
        parsed = run_async(DNSMessage.read_from((bytes(original), ENDPOINT)))

        assert parsed is not None
        assert (
            parsed.is_response,
            parsed.is_authoritative,
            parsed.is_truncated,
            parsed.is_recursive,
            parsed.recursion_available,
            parsed.is_authentic,
            parsed.checking_disabled,
            parsed.response_code,
            parsed.operation_code,
        ) == (True, True, True, True, True, True, True, ResponseCode.NAME_ERROR, OpCode.UPDATE)

    def test_returns_none_for_too_short_a_buffer(self):
        """Data too short to even hold the fixed header fails cleanly with
        `None`, rather than letting the underlying `struct`/`IndexError`
        propagate."""
        assert run_async(DNSMessage.read_from((b"\x00\x01", ENDPOINT))) is None

    def test_returns_none_when_a_section_count_lies(self):
        """A header claiming more entries than the buffer actually holds
        fails cleanly with `None`."""
        message = DNSMessage.query("example.com")
        data = bytes(message)[:12] + b"\xff\xff"  # qdcount replaced with a huge lie, no question data follows
        assert run_async(DNSMessage.read_from((data, ENDPOINT))) is None


class TestDNSMessageTSIGSigning:
    """Appending an RFC 2845 TSIG signature record to a message's
    additional section."""

    def test_appends_a_tsig_record_for_the_signing_key(self):
        """The appended record is owned by the key name, is CLASS ANY, and
        has type TSIG."""
        message = DNSMessage.query("example.com")
        message.sign_tsig("key.example.com.", b"shared-secret")

        tsig_record = message.additional[-1]
        assert tsig_record.rtype == RecordType.TSIG
        assert tsig_record.rclass == RecordClass.ANY
        assert tsig_record.rname == DNSKey._encode_domain("key.example.com.")

    def test_signature_matches_an_independent_rfc_2845_computation(self):
        """The HMAC covers the message bytes (before the TSIG record was
        added) plus the RFC 2845 §3.4.2 TSIG variables - recomputing that
        independently should reproduce the exact same MAC."""
        message = DNSMessage.query("example.com", RecordType.A)
        message_bytes_before_signing = bytes(message)
        secret = b"shared-secret"
        signed_time = 1_700_000_000

        with patch("gossip.dns.message.time.time", return_value=float(signed_time)):
            message.sign_tsig("key.example.com.", secret)

        encoded_key_name = DNSKey._encode_domain("key.example.com.")
        encoded_algorithm = DNSKey._encode_domain("hmac-sha256.")
        tsig_variables = (
            encoded_key_name
            + struct.pack("!IH", RecordClass.ANY, 0)  # CLASS, TTL
            + encoded_algorithm
            + signed_time.to_bytes(6, byteorder="big")
            + struct.pack("!HHH", 300, 0, 0)  # fudge, error, other len
        )
        expected_mac = hmac.new(secret, message_bytes_before_signing + tsig_variables, hashlib.sha256).digest()

        rdata = message.additional[-1].rdata
        mac_size_offset = len(encoded_algorithm) + 6 + 2  # skip algorithm, time signed, fudge
        (mac_size,) = struct.unpack_from("!H", rdata, mac_size_offset)
        mac = rdata[mac_size_offset + 2 : mac_size_offset + 2 + mac_size]
        assert mac == expected_mac

    def test_a_different_secret_produces_a_different_signature(self):
        """Signing is actually keyed by the secret, not some fixed value."""
        first = DNSMessage.query("example.com")
        second = DNSMessage.query("example.com")
        with patch("gossip.dns.message.time.time", return_value=0.0):
            first.sign_tsig("key.example.com.", b"secret-one")
            second.sign_tsig("key.example.com.", b"secret-two")
        assert first.additional[-1].rdata != second.additional[-1].rdata

    def test_selects_algorithm_by_name(self):
        """A non-default algorithm name selects a different hash function,
        producing a MAC of that algorithm's digest size."""
        message = DNSMessage.query("example.com")
        message.sign_tsig("key.example.com.", b"shared-secret", algorithm="hmac-sha1.")
        rdata = message.additional[-1].rdata
        encoded_algorithm = DNSKey._encode_domain("hmac-sha1.")
        assert rdata[: len(encoded_algorithm)] == encoded_algorithm
        mac_size_offset = len(encoded_algorithm) + 6 + 2
        (mac_size,) = struct.unpack_from("!H", rdata, mac_size_offset)
        assert mac_size == hashlib.sha1().digest_size


class TestDNSMessageRepr:
    """`repr()` formatting for outgoing queries and incoming responses."""

    def test_query_repr_shows_the_question(self):
        """A non-response message's repr names its operation and first
        question."""
        assert repr(DNSMessage.query("example.com", RecordType.A)) == "QUERY(A: example.com)"

    def test_query_repr_shows_the_recursive_flag(self):
        """A recursive query's repr calls that out."""
        assert repr(DNSMessage.query("example.com", recursive=True)) == "QUERY(A: example.com, recursive)"

    def test_response_repr_with_no_flags_or_sections(self):
        """A bare response shows just its response code."""
        assert repr(DNSMessage(is_response=True, response_code=ResponseCode.NO_ERROR)) == "RESPONSE(NO_ERROR)"

    def test_response_repr_lists_set_flags(self):
        """Set response flags are named in the repr, comma-separated."""
        message = DNSMessage(
            is_response=True,
            is_authoritative=True,
            is_truncated=True,
            is_authentic=True,
            response_code=ResponseCode.NO_ERROR,
        )
        assert repr(message) == "RESPONSE(NO_ERROR, authoritative, truncated, authentic)"

    def test_response_repr_shows_non_empty_sections(self):
        """Non-empty sections are named and shown after a colon, in
        answers/authorities/additional order; empty sections are omitted."""
        message = DNSMessage(
            is_response=True,
            response_code=ResponseCode.NO_ERROR,
            answers=[Record.address("example.com", IPv4Address("1.2.3.4"), timedelta(seconds=300))],
            authorities=[Record.domain_target("example.com", RecordType.NS, "ns1.example.com", timedelta(seconds=300))],
            additional=[Record.tsig(DNSKey._encode_domain("key.example.com"), b"signature")],
        )
        assert repr(message) == (
            f"RESPONSE(NO_ERROR: answers={message.answers}, "
            f"authorities={message.authorities}, additional={message.additional})"
        )

    def test_response_repr_combines_flags_and_sections(self):
        """Flags and sections both appear together when both are present."""
        message = DNSMessage(
            is_response=True,
            is_authoritative=True,
            response_code=ResponseCode.NO_ERROR,
            answers=[Record.address("example.com", IPv4Address("1.2.3.4"), timedelta(seconds=300))],
        )
        assert repr(message) == f"RESPONSE(NO_ERROR, authoritative: answers={message.answers})"
