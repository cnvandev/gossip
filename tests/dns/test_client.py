import asyncio
import contextlib
from datetime import timedelta
from ipaddress import IPv4Address

import pytest

from gossip.dns.client import DNSClient
from gossip.dns.constants import ResponseCode
from gossip.dns.message import DNSMessage, RecordType
from gossip.dns.model import Record
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio

from ..support.asyncio import SequencedReplyProtocol, StaticReplyProtocol

LOOPBACK = IPv4Address("127.0.0.1")
TTL = timedelta(seconds=300)


class TestDNSClientInit:
    """Building a `DNSClient`."""

    def test_defaults_to_a_prompter(self):
        """Omitting `prompter` builds a real one."""
        client = DNSClient(radio=Radio.loopback())
        assert isinstance(client.prompter, Prompter)

    def test_stores_the_given_prompter(self):
        """A given `prompter` is stored as-is."""
        prompter = Prompter(DNSMessage.read_from, radio=Radio.loopback())
        client = DNSClient(prompter=prompter)
        assert client.prompter is prompter


class TestDNSClientNameserver:
    """`DNSClient.nameserver()` finds the authoritative nameserver for a
    domain, following delegation (with or without glue records) as
    needed."""

    async def test_returns_the_root_directly_when_its_already_authoritative(self):
        """A root that answers authoritatively is the nameserver."""
        response = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            authority = await client.nameserver("example.com", roots=[LOOPBACK], port=port)

            assert authority == LOOPBACK

    async def test_returns_none_for_an_error_response(self):
        """A response with a non-`NO_ERROR` code yields no nameserver."""
        response = DNSMessage(is_response=True, response_code=ResponseCode.NAME_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            authority = await client.nameserver("example.com", roots=[LOOPBACK], port=port)

            assert authority is None

    async def test_returns_none_for_an_unparseable_response(self):
        """A response the deserializer can't parse yields no nameserver."""
        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(b"x"), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            authority = await client.nameserver("example.com", roots=[LOOPBACK], port=port)

            assert authority is None

    async def test_recurses_using_glue_records_when_delegated(self):
        """A non-authoritative response with glue records recurses to the
        delegated nameserver directly, without an extra resolve."""
        delegation = DNSMessage(
            is_response=True,
            response_code=ResponseCode.NO_ERROR,
            authorities=[Record.domain_target("example.com", RecordType.NS, "ns1.example.com", TTL)],
            additional=[Record.address("ns1.example.com", LOOPBACK, TTL)],
        )
        authoritative = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: SequencedReplyProtocol([bytes(delegation), bytes(authoritative)]), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            authority = await client.nameserver("example.com", roots=[LOOPBACK], port=port)

            assert authority == LOOPBACK

    async def test_resolves_the_authority_domain_when_theres_no_glue_record(self):
        """A non-authoritative response with authorities but no glue
        records resolves the authority's own IP first, then recurses to it."""
        # Round trips, in order: (1) the initial delegation with no glue
        # record, (2)-(3) resolving `ns1.example.com`'s own IP (a nested
        # authoritative check, then the actual query), and (4) the final
        # authoritative check against that resolved IP.
        delegation_no_glue = DNSMessage(
            is_response=True,
            response_code=ResponseCode.NO_ERROR,
            authorities=[Record.domain_target("example.com", RecordType.NS, "ns1.example.com", TTL)],
        )
        authoritative_empty = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)
        ns1_address = DNSMessage(
            is_response=True,
            is_authoritative=True,
            response_code=ResponseCode.NO_ERROR,
            answers=[Record.address("ns1.example.com", LOOPBACK, TTL)],
        )

        loop = asyncio.get_running_loop()
        replies = [delegation_no_glue, authoritative_empty, ns1_address, authoritative_empty]
        server, _ = await loop.create_datagram_endpoint(lambda: SequencedReplyProtocol([bytes(reply) for reply in replies]), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            authority = await client.nameserver("example.com", roots=[LOOPBACK], port=port)

            assert authority == LOOPBACK

    async def test_returns_none_when_the_authority_domain_cant_be_resolved(self):
        """If resolving the authority's own IP fails outright (no answer
        at all), that's treated the same as not finding one - `None`,
        rather than letting the failure propagate uncaught."""
        delegation_no_glue = DNSMessage(
            is_response=True,
            response_code=ResponseCode.NO_ERROR,
            authorities=[Record.domain_target("example.com", RecordType.NS, "ns1.example.com", TTL)],
        )
        authoritative_empty = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)
        # The actual query for `ns1.example.com` succeeds, but has neither
        # an IP answer nor a CNAME to follow - resolve_ip() raises.
        no_answer = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)

        loop = asyncio.get_running_loop()
        replies = [delegation_no_glue, authoritative_empty, no_answer]
        server, _ = await loop.create_datagram_endpoint(lambda: SequencedReplyProtocol([bytes(reply) for reply in replies]), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            authority = await client.nameserver("example.com", roots=[LOOPBACK], port=port)

            assert authority is None


class TestDNSClientQuery:
    """`DNSClient.query()` resolves the nameserver for a domain, then
    sends it the actual query directly."""

    async def test_returns_the_response_from_the_resolved_nameserver(self):
        """The response from the (already-authoritative) nameserver is
        returned as-is."""
        answer = Record.address("example.com", IPv4Address("93.184.216.34"), TTL)
        response = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR, answers=[answer])

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.query("example.com", roots=[LOOPBACK], port=port)

            assert result is not None
            assert result.answers == [answer]

    async def test_returns_none_when_no_nameserver_is_found(self):
        """With no authoritative nameserver found at all, returns `None`
        rather than querying anything further."""
        response = DNSMessage(is_response=True, response_code=ResponseCode.NAME_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.query("example.com", roots=[LOOPBACK], port=port)

            assert result is None


class TestDNSClientResolveIp:
    """`DNSClient.resolve_ip()` queries for a domain's IP, following a
    single level of CNAME indirection if that's all it gets back."""

    async def test_returns_an_answers_ip_directly(self):
        """An A/AAAA answer's IP is returned directly."""
        answer = Record.address("example.com", IPv4Address("93.184.216.34"), TTL)
        response = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR, answers=[answer])

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            ip = await client.resolve_ip("example.com", roots=[LOOPBACK], port=port)

            assert ip == IPv4Address("93.184.216.34")

    async def test_follows_a_cname_when_theres_no_direct_answer(self):
        """A CNAME-only answer is followed to resolve the target's own IP."""
        # Each domain resolved (`example.com`, then `target.example.com`)
        # costs two round trips: one to confirm the nameserver is
        # authoritative, one for the actual query.
        authoritative_empty = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)
        cname_response = DNSMessage(
            is_response=True,
            is_authoritative=True,
            response_code=ResponseCode.NO_ERROR,
            answers=[Record.domain_target("example.com", RecordType.CNAME, "target.example.com", TTL)],
        )
        a_response = DNSMessage(
            is_response=True,
            is_authoritative=True,
            response_code=ResponseCode.NO_ERROR,
            answers=[Record.address("target.example.com", IPv4Address("93.184.216.34"), TTL)],
        )

        loop = asyncio.get_running_loop()
        replies = [authoritative_empty, cname_response, authoritative_empty, a_response]
        server, _ = await loop.create_datagram_endpoint(lambda: SequencedReplyProtocol([bytes(reply) for reply in replies]), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            ip = await client.resolve_ip("example.com", roots=[LOOPBACK], port=port)

            assert ip == IPv4Address("93.184.216.34")

    async def test_raises_when_no_nameserver_is_found_at_all(self):
        """No nameserver found at all raises, rather than returning
        something falsy."""
        response = DNSMessage(is_response=True, response_code=ResponseCode.NAME_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            with pytest.raises(ValueError):
                await client.resolve_ip("example.com", roots=[LOOPBACK], port=port)

    async def test_raises_when_the_response_has_neither_an_ip_nor_a_cname(self):
        """A nameserver that responds, but with no IP answer and no
        CNAME to follow, also raises."""
        response = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            with pytest.raises(ValueError):
                await client.resolve_ip("example.com", roots=[LOOPBACK], port=port)


class TestDNSClientUpdate:
    """`DNSClient.update()` resolves the zone's nameserver, then sends it
    an RFC 2136 update message."""

    async def test_sends_the_update_and_returns_the_response(self):
        """The nameserver's response to the update is returned."""
        response = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.update("example.com", "host.example.com", IPv4Address("10.0.0.1"), TTL, roots=[LOOPBACK], port=port)

            assert result is not None
            assert result.response_code == ResponseCode.NO_ERROR

    async def test_returns_none_when_no_nameserver_is_found(self):
        """With no authoritative nameserver found, returns `None`."""
        response = DNSMessage(is_response=True, response_code=ResponseCode.NAME_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.update("example.com", "host.example.com", IPv4Address("10.0.0.1"), TTL, roots=[LOOPBACK], port=port)

            assert result is None


class TestDNSClientInsert:
    """`DNSClient.insert()` resolves the zone's nameserver, then sends it
    an RFC 2136 insert message."""

    async def test_sends_the_insert_and_returns_the_response(self):
        """The nameserver's response to the insert is returned."""
        response = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.insert("example.com", "host.example.com", IPv4Address("10.0.0.1"), TTL, roots=[LOOPBACK], port=port)

            assert result is not None
            assert result.response_code == ResponseCode.NO_ERROR

    async def test_returns_none_when_no_nameserver_is_found(self):
        """With no authoritative nameserver found, returns `None`."""
        response = DNSMessage(is_response=True, response_code=ResponseCode.NAME_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.insert("example.com", "host.example.com", IPv4Address("10.0.0.1"), TTL, roots=[LOOPBACK], port=port)

            assert result is None


class TestDNSClientDelete:
    """`DNSClient.delete()` resolves the zone's nameserver, then sends it
    an RFC 2136 delete message."""

    async def test_sends_the_delete_and_returns_the_response(self):
        """The nameserver's response to the delete is returned."""
        response = DNSMessage(is_response=True, is_authoritative=True, response_code=ResponseCode.NO_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.delete("example.com", "host.example.com", roots=[LOOPBACK], port=port)

            assert result is not None
            assert result.response_code == ResponseCode.NO_ERROR

    async def test_returns_none_when_no_nameserver_is_found(self):
        """With no authoritative nameserver found, returns `None`."""
        response = DNSMessage(is_response=True, response_code=ResponseCode.NAME_ERROR)

        loop = asyncio.get_running_loop()
        server, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(response)), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(server):
            _, port = server.get_extra_info("sockname")
            client = DNSClient(radio=Radio.loopback())
            result = await client.delete("example.com", "host.example.com", roots=[LOOPBACK], port=port)

            assert result is None
