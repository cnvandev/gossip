"""Synthetic `Question`/`Record` instances for the dns test suite.

Not a test module - imported by test_model.py and test_serialization.py.
"""

from datetime import timedelta

from gossip.dns.constants import RecordClass, RecordType
from gossip.dns.model import DNSKey, Question, Record


class DummyQuestion(Question):
    """A question for a fixed example domain, A/IN, unless overridden."""

    def __init__(self, domain: str = "example.com", rtype: RecordType = RecordType.A, rclass: RecordClass = RecordClass.IN):
        super().__init__(DNSKey._encode_domain(domain), rtype, rclass)


class DummyRecord(Record):
    """A record for a fixed example domain, A/IN, 300s TTL, and empty RDATA
    unless overridden. For the RDATA shapes DNS actually defines (address,
    domain-target, MX), use `Record.address()`/`.domain_target()`/`.mx()`
    directly - they're real factories on the production class, not test-only."""

    def __init__(
        self,
        domain: str = "example.com",
        rtype: RecordType = RecordType.A,
        rclass: RecordClass = RecordClass.IN,
        ttl: timedelta = timedelta(seconds=300),
        rdata: bytes = b"",
    ):
        super().__init__(DNSKey._encode_domain(domain), rtype, rclass, ttl, rdata)
