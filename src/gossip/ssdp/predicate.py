from gossip.internet.predicate import URIPredicate
from gossip.ssdp.uri import SSDPTarget


class SSDPTargetPredicate(URIPredicate):
    """A predicate for matching an SSDP search target (`ST`) against the
    targets a resource can represent.

    Parses into `SSDPTarget` rather than a plain `URI`, so comparison (via
    the inherited `URIPredicate.compare()`) resolves to
    `SSDPTarget.covers()`, not the generic `URI.covers()`.
    """

    def parse(self, input: str) -> SSDPTarget:
        return SSDPTarget.parse(input)
