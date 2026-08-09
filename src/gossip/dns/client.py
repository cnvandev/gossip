import logging
import random
from collections.abc import Sequence
from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address

from gossip.dns.constants import ROOT_SERVERS, RecordClass, ResponseCode
from gossip.dns.message import DNSMessage, RecordType
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio

log = logging.getLogger(__name__)


class DNSClient:
    """A client for looking up IP addresses from domain names using DNS."""

    """The prompter which creates connections to DNS servers & sends mesages."""
    prompter: Prompter[DNSMessage]

    def __init__(self, prompter: Prompter[DNSMessage] | None = None, radio: Radio | None = None):
        if prompter is None:
            prompter = self.prompter = Prompter(DNSMessage.read_from, radio=radio)
        self.prompter = prompter

    async def resolve_ip(self, domain: str, qtype: RecordType = RecordType.A) -> IPv4Address | IPv6Address:
        response = await self.query(domain, qtype)
        if response is None:
            raise ValueError(f"No IP retrievable for {domain}")
        else:
            ip_addresses = tuple(filter(None, (answer.decode_ip() for answer in response.answers)))
            if ip_addresses:
                return random.choice(ip_addresses)

            # Follow CNAMEs if present
            cnames = tuple(filter(None, (record.decode_domain() for record in response.answers if record.rtype == RecordType.CNAME)))
            if cnames:
                return await self.resolve_ip(random.choice(cnames), qtype)

            raise ValueError(f"No IP retrievable for {domain}")

    async def nameserver(self, domain: str, roots: Sequence[IPv4Address | IPv6Address] | None = None) -> IPv4Address | IPv6Address | None:
        """Gets the IP addresses for the authoritative nameservers for a domain."""
        if roots is None:
            roots = tuple(ROOT_SERVERS.values())
        authority = random.choice(roots)
        root_endpoint = Endpoint(authority, 53)

        request = DNSMessage.query(domain, RecordType.A)
        response = await self.prompter.prompt_udp(request, root_endpoint)
        if response is not None:
            log.debug(response)
            if response.response_code == ResponseCode.NO_ERROR:
                if response.is_authoritative:
                    # The queried nameserver is authoritative for this domain.
                    return authority
                else:
                    log.debug("Non-authoritative response from `%s` with %d authorities & %d additional records.", root_endpoint, len(response.authorities), len(response.additional))

                    if response.additional:
                        # We have glue records, IP addresses for the NS records
                        # in `response.authorities` so we can recurse directly.
                        # TODO: this assumes the glue records are valid, which
                        # I guess isn't guaranteed to be the case.
                        ns_addresses = tuple(filter(None, (record.decode_ip() for record in response.additional if record.rtype == RecordType.A)))
                        log.debug("Found glue records, recursing...")
                        return await self.nameserver(domain, ns_addresses)
                    elif response.authorities:
                        # No glue records found, we have to look up the IP
                        # addresses for the authority records.
                        authority_domain = random.choice(tuple(filter(None, (record.decode_domain() for record in response.authorities))))
                        log.debug("No glue records, resolving `%s`.", authority_domain)
                        ns_ip = await self.resolve_ip(authority_domain)
                        if ns_ip is None:
                            log.error("No IP addresses found for authority `%s`", authority_domain)
                            return None
                        else:
                            log.debug("Found IP for authority: %s", ns_ip)
                            return await self.nameserver(domain, [ns_ip])
            else:
                log.error("Error received: %s", response.response_code)
                return None
        else:
            log.error("No response decoded from `%s`", authority)
            return None

    async def query(self, domain: str, qtype: RecordType = RecordType.A, recursive: bool = False) -> DNSMessage | None:
        """Queries the DNS server of a domain for specific record types."""
        authority = await self.nameserver(domain)
        if authority is not None:
            log.debug("Querying nameserver `%s` for `%s`", authority, domain)
            ns_endpoint = Endpoint(authority, 53)
            message = DNSMessage.query(domain, qtype, recursive=recursive)
            return await self.prompter.prompt_udp(message, ns_endpoint)
        else:
            log.error("No nameservers found for `%s`", domain)
            return None

    async def update(self, zone: str, hostname: str, ip_address: IPv4Address, ttl: timedelta | int, rtype: RecordType = RecordType.A, rclass: RecordClass = RecordClass.IN) -> DNSMessage | None:
        authority = await self.nameserver(zone)
        if authority is not None:
            log.debug("Updating nameserver `%s` for `%s`", authority, hostname)
            ns_endpoint = Endpoint(authority, 53)
            message = DNSMessage.update(zone, hostname, ip_address, ttl, rtype, rclass)
            return await self.prompter.prompt_udp(message, ns_endpoint)
        else:
            log.error("No nameservers found for `%s`", zone)
            return None

    async def insert(self, zone: str, hostname: str, ip_address: IPv4Address, ttl: timedelta | int, rtype: RecordType = RecordType.A, rclass: RecordClass = RecordClass.IN) -> DNSMessage | None:
        authority = await self.nameserver(zone)
        if authority is not None:
            log.debug("Inserting to nameserver `%s` for `%s`", authority, hostname)
            ns_endpoint = Endpoint(authority, 53)
            message = DNSMessage.insert(zone, hostname, ip_address, ttl, rtype, rclass)
            return await self.prompter.prompt_udp(message, ns_endpoint)
        else:
            log.error("No nameservers found for `%s`", zone)
            return None

    async def delete(self, zone: str, hostname: str, rtype: RecordType = RecordType.A, rclass: RecordClass = RecordClass.IN) -> DNSMessage | None:
        authority = await self.nameserver(zone)
        if authority is not None:
            log.debug("Deleting from nameserver `%s` for `%s`", authority, hostname)
            ns_endpoint = Endpoint(authority, 53)
            message = DNSMessage.delete(zone, hostname, rtype, rclass)
            return await self.prompter.prompt_udp(message, ns_endpoint)
        else:
            log.error("No nameservers found for `%s`", zone)
            return None
