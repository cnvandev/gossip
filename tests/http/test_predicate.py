from langcodes import Language

from gossip.http.predicate import LanguagePredicate, MediaTypePredicate, StringPredicate
from gossip.internet.mime import MediaType


class TestMediaTypePredicate:
    """Matching an `Accept`-style header against a set of offered media
    types, honoring wildcards and quality ranking."""

    def test_accepts_exact_match(self):
        """An offered type that exactly matches the header is accepted."""
        predicate = MediaTypePredicate([MediaType.text("html")])
        accepted = predicate.accepts("text/html")
        assert accepted == ((MediaType.text("html"), {}),)

    def test_accepts_wildcard(self):
        """An offered type is accepted when the header specifies a wildcard
        that covers it."""
        predicate = MediaTypePredicate([MediaType.text("html")])
        accepted = predicate.accepts("*/*")
        assert accepted == ((MediaType.text("html"), {}),)

    def test_rejects_unlisted_type(self):
        """A type that isn't among the offered options is rejected, even if
        the header explicitly names it."""
        predicate = MediaTypePredicate([MediaType.text("html")])
        assert predicate.accepts("image/png") == ()

    def test_prefers_highest_quality_group(self):
        """When several offered types are individually acceptable but at
        different qualities, only the highest-quality group should be
        returned - lower-quality acceptable options are not fallbacks once a
        higher one has already matched."""
        predicate = MediaTypePredicate([MediaType.application("json"), MediaType.text("html")])
        accepted = predicate.accepts("application/json;q=0.5, text/html;q=0.9")
        assert accepted == ((MediaType.text("html"), {}),)

    def test_falls_through_to_lower_quality_if_higher_is_unsupported(self):
        """When the highest-quality entry in the header isn't among the
        offered options, matching falls through to the next-highest quality
        that is."""
        predicate = MediaTypePredicate([MediaType.application("json")])
        accepted = predicate.accepts("text/html;q=0.9, application/json;q=0.5")
        assert accepted == ((MediaType.application("json"), {}),)

    def test_multiple_offered_types_can_match_same_quality(self):
        """A wildcard at one quality level can accept more than one offered
        type at once."""
        predicate = MediaTypePredicate([MediaType.text("html"), MediaType.application("json")])
        accepted = predicate.accepts("*/*")
        assert {option for option, _ in accepted} == {MediaType.text("html"), MediaType.application("json")}


class TestStringPredicate:
    """Matching a header value against a set of offered strings by exact
    equality."""

    def test_accepts_listed_value(self):
        """An offered value that appears in the header is accepted."""
        predicate = StringPredicate(["en", "fr"])
        assert predicate.accepts("en") == (("en", {}),)

    def test_rejects_unlisted_value(self):
        """A value that isn't among the offered options is rejected."""
        predicate = StringPredicate(["en", "fr"])
        assert predicate.accepts("de") == ()

    def test_prefers_highest_quality(self):
        """Between two offered values at different qualities, only the
        higher-quality one is returned."""
        predicate = StringPredicate(["en", "fr"])
        assert predicate.accepts("en;q=0.2, fr;q=0.8") == (("fr", {}),)


class TestLanguagePredicate:
    """Matching an `Accept-Language`-style header against offered languages
    by linguistic distance rather than exact equality."""

    def test_accepts_close_language_match(self):
        """`en-US` in the header is accepted against an offered plain `en`,
        since the two are close enough to count as the same language.

        Options must be pre-parsed `Language` objects, not raw strings -
        `compare()` calls `.distance()` on each option directly. The class
        is already correctly typed as `RequestPredicate[Language]`, so a
        type checker would catch a raw `["en"]` list; this test documents
        the concrete runtime effect of getting that wrong.
        """
        predicate = LanguagePredicate([Language.get("en")])
        accepted = predicate.accepts("en-US")
        assert len(accepted) == 1
        assert str(accepted[0][0]) == "en"

    def test_rejects_distant_language(self):
        """A linguistically unrelated language in the header is rejected."""
        predicate = LanguagePredicate([Language.get("en")])
        assert predicate.accepts("ja") == ()


class TestRequestPredicateAccepts:
    """Behavior of the shared quality-ranking algorithm in
    `RequestPredicate.accepts()`, independent of which concrete predicate
    subclass is doing the comparing - exercised here through the simplest
    one, `StringPredicate`."""

    def test_missing_quality_defaults_to_one(self):
        """A header value with no `q` parameter is treated as the maximum
        weight, `1` (RFC 9110 §12.4.2) - here it wins out over another
        value with an explicit, lower `q`."""
        predicate = StringPredicate(["en", "fr"])
        assert predicate.accepts("en;q=0.5, fr") == (("fr", {}),)

    def test_tolerates_parameter_without_equals_sign(self):
        """A malformed parameter with no `=` (e.g. a bare `charset` instead
        of `charset=utf-8`) doesn't crash matching - it's treated as a
        parameter with an empty value, rather than raising."""
        predicate = StringPredicate(["en"])
        assert predicate.accepts("en;charset") == (("en", {"charset": ""}),)
