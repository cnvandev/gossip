from gossip.ssdp.predicate import SSDPTargetPredicate
from gossip.ssdp.uri import SSDPTarget


class TestSSDPTargetPredicate:
    """Matching a search request's `ST` header against a set of targets a
    resource can represent, via `SSDPTarget.covers()`."""

    def test_accepts_exact_match(self):
        """An offered target that exactly matches the header is accepted."""
        predicate = SSDPTargetPredicate([SSDPTarget.root()])
        assert predicate.accepts("upnp:rootdevice") == ((SSDPTarget.root(), {}),)

    def test_accepts_ssdp_all_for_every_offered_target(self):
        """`ssdp:all` in the header matches every offered target at once."""
        predicate = SSDPTargetPredicate([SSDPTarget.root(), SSDPTarget.device_type("Foo")])
        accepted = predicate.accepts("ssdp:all")
        assert {option for option, _ in accepted} == {SSDPTarget.root(), SSDPTarget.device_type("Foo")}

    def test_rejects_unlisted_target(self):
        """A target that isn't among the offered options is rejected, even
        though it's well-formed."""
        predicate = SSDPTargetPredicate([SSDPTarget.root()])
        assert predicate.accepts("urn:schemas-upnp-org:device:Foo:1") == ()
