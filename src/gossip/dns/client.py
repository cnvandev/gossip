import asyncio
import logging
import random
import sys
from collections.abc import Sequence
from ipaddress import IPv4Address, IPv6Address

from gossip.dns.constants import ROOT_SERVERS
from gossip.dns.message import DNSMessage, RecordType
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio

log = logging.getLogger(__name__)


class DNSClient:
    """A client for looking up IP addresses from domain names using DNS."""

    prompter: Prompter[DNSMessage]

    def __init__(self, prompter: Prompter[DNSMessage] | None = None, radio: Radio | None = None):
        if prompter is None:
            prompter = self.prompter = Prompter(DNSMessage.read_from)
        self.prompter = prompter

    async def resolve_ip(self, domain: str, qtype: RecordType = RecordType.A) -> IPv4Address | IPv6Address:
        response = await self.query(domain, qtype)
        if response is None:
            raise ValueError(f"No IP retrievable for {domain}")
        else:
            ip_addresses = tuple(filter(None, (answer.decode_ip() for answer in response.answers)))
            return random.choice(ip_addresses)

    async def query(self, domain: str, qtype: RecordType = RecordType.A, recursive: bool = False, authorities: Sequence[IPv4Address | IPv6Address] | None = None) -> DNSMessage | None:
        # TODO: break this up into authority-finding and record-finding.
        if authorities is None:
            authorities = tuple(ROOT_SERVERS.values())
        authority = random.choice(authorities)
        log.debug("Chosen authority: %s", authority)
        message = DNSMessage.query(domain, qtype, recursive=recursive)
        root_endpoint = Endpoint(authority, 53)
        response = await self.prompter.prompt_udp(message, root_endpoint)

        if response is not None:
            for answer in response.answers:
                log.debug("Answer: %r", answer)
            for authority in response.authorities:
                log.debug("Authority: %r", authority)
            for additional in response.additional:
                log.debug("Additional: %r", additional)

            if response.answers or recursive:
                cnames = tuple(filter(None, (record.decode_domain() for record in response.answers if record.rtype == RecordType.CNAME)))
                if len(cnames) == len(response.answers):
                    log.debug("Found CNAME-only answers, following `%s`.", cnames[0])
                    new_authorities = tuple(ROOT_SERVERS.values())
                    return await self.query(cnames[0], qtype, authorities=new_authorities)
                else:
                    log.debug("Found answers or recursive query, returning response.")
                    return response
            elif response.authorities:
                log.debug("Non-authoritative response from `%s` with %d authorities & %d additional records.", root_endpoint, len(response.authorities), len(response.additional))

                if response.additional:
                    next_authorities = tuple(filter(None, (record.decode_ip() for record in response.additional if record.rtype == qtype)))
                    log.debug("Querying %s for domain", next_authorities)
                    return await self.query(domain, qtype, authorities=next_authorities)
                else:
                    nameserver = random.choice(tuple(filter(None, (record.decode_domain() for record in response.authorities))))
                    log.debug("No additional records, looking up nameserver records for `%s`.", nameserver)
                    ns_response = await self.query(nameserver, qtype)
                    if ns_response is not None:
                        nameserver_ips = filter(None, (answer.decode_ip() for answer in ns_response.answers))
                        return await self.query(domain, qtype, authorities=tuple(nameserver_ips))
                    else:
                        log.warning("Could not resolve intermediary record `%s`", nameserver)
                        return None
            else:
                log.debug("No authorities or answers, returning response.")
                return response
        else:
            return response


async def lookup(domain: str):
    client = DNSClient()
    ip_address = await client.resolve_ip(domain)
    log.info("%s -> %s", domain, ip_address)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    asyncio.run(lookup("chris.vandevel.de"), debug=True)
