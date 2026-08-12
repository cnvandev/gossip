from gossip.internet.mime import MediaType


class TestMediaTypeParsing:
    """Constructing a `MediaType` - from a `type/subtype` string, from one
    of the top-level-type factories, or directly - and converting it back
    to that same string form."""

    def test_parse(self):
        """Parsing a `"type/subtype"` string yields a `MediaType` with
        those exact type and subtype fields."""
        assert MediaType.parse("text/html") == MediaType("text", "html")

    def test_str(self):
        """Converting a `MediaType` to a string produces its `type/subtype`
        form."""
        assert str(MediaType.text("html")) == "text/html"

    def test_factories(self):
        """Each top-level-type factory (and the `*/*` wildcard factory)
        builds a `MediaType` with the type its name promises and the given
        subtype."""
        assert MediaType.application("json") == MediaType("application", "json")
        assert MediaType.image("png") == MediaType("image", "png")
        assert MediaType.video("mp4") == MediaType("video", "mp4")
        assert MediaType.message("http") == MediaType("message", "http")
        assert MediaType.all() == MediaType("*", "*")


class TestMediaTypeCovers:
    """Whether one `MediaType` matches every representation another one
    matches - across exact matches, wildcards, and types that don't relate
    at all."""

    def test_covers_itself(self):
        """A media type always covers itself."""
        html = MediaType.text("html")
        assert html.covers(html)

    def test_wildcard_subtype_covers_concrete_subtype(self):
        """A wildcard subtype covers a concrete one, but not the other way
        around."""
        assert MediaType.text("*").covers(MediaType.text("html"))
        assert not MediaType.text("html").covers(MediaType.text("*"))

    def test_full_wildcard_covers_everything(self):
        """`*/*` covers every media type, but no concrete type covers
        `*/*`."""
        assert MediaType.all().covers(MediaType.text("html"))
        assert not MediaType.text("html").covers(MediaType.all())

    def test_unrelated_types_cover_neither_direction(self):
        """Two types with different top-level types cover neither each
        other."""
        html = MediaType.text("html")
        png = MediaType.image("png")
        assert not html.covers(png)
        assert not png.covers(html)

    def test_wildcard_subtype_does_not_cover_a_different_type(self):
        """A wildcard subtype only covers types that share its top-level
        type."""
        text_star = MediaType.text("*")
        png = MediaType.image("png")
        assert not text_star.covers(png)

    def test_accepts_plain_tuples_not_just_mediatype(self):
        """A plain `(type, subtype)` tuple works as the argument to
        `covers()`, not just a `MediaType` instance."""
        assert MediaType.text("*").covers(("text", "html"))


class TestMediaTypeOrdering:
    """Whether `<`, `<=`, `>`, and `>=` agree with `covers()` - including
    staying `False` on every operator for two types that simply don't
    relate."""

    def test_identical_types_are_reflexive_on_every_operator(self):
        """A media type is always `<=` and `>=` itself, and never strictly
        `<` or `>` itself."""
        html = MediaType.text("html")
        assert html <= html
        assert html >= html
        assert not (html < html)
        assert not (html > html)

    def test_concrete_type_is_strictly_smaller_than_wildcard_subtype(self):
        """A concrete subtype is strictly less than a matching wildcard
        subtype, and never greater than or equal to it - and the
        relationship mirrors exactly in the other direction."""
        html = MediaType.text("html")
        text_star = MediaType.text("*")
        assert html <= text_star
        assert html < text_star
        assert not (html >= text_star)
        assert not (html > text_star)

        # And the relationship is a mirror image from the other side.
        assert text_star >= html
        assert text_star > html
        assert not (text_star <= html)
        assert not (text_star < html)

    def test_concrete_type_is_strictly_smaller_than_full_wildcard(self):
        """A concrete type is strictly less than the full wildcard `*/*`."""
        html = MediaType.text("html")
        star = MediaType.all()
        assert html < star
        assert star > html

    def test_unrelated_types_fail_every_comparison(self):
        """Two types that don't relate at all (neither covers the other)
        must be `False` under *all four* operators, not just `<=`."""
        html = MediaType.text("html")
        png = MediaType.image("png")
        assert not (html <= png)
        assert not (html >= png)
        assert not (html < png)
        assert not (html > png)
        assert not (png <= html)
        assert not (png >= html)
        assert not (png < html)
        assert not (png > html)

    def test_wildcard_subtype_does_not_cover_different_type(self):
        """A wildcard subtype doesn't cover a type with a different
        top-level type, in either comparison direction."""
        text_star = MediaType.text("*")
        png = MediaType.image("png")
        assert not (png <= text_star)
        assert not (text_star >= png)

    def test_operators_accept_plain_tuples_not_just_mediatype(self):
        """Every comparison operator works with a plain `(type, subtype)`
        tuple on either side, not just a `MediaType` instance."""
        html = MediaType.text("html")
        assert html <= ("text", "*")
        assert html < ("text", "*")
        assert ("text", "*") > html
        assert ("text", "*") >= html
