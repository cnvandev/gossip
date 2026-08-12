import platform

from gossip.internet.product import Product, ProductStack, SemanticVersion, stack


class TestSemanticVersion:
    """Parsing a dotted version string into a `SemanticVersion`, with and
    without its trailing components."""

    def test_parse_full(self):
        """A three-part `major.minor.patch` string parses into all three
        fields."""
        assert SemanticVersion.parse("1.2.3") == SemanticVersion(1, 2, 3)

    def test_parse_major_minor(self):
        """A two-part `major.minor` string parses into those two fields,
        leaving `patch` at its `None` default."""
        assert SemanticVersion.parse("2.0") == SemanticVersion(2, 0)

    def test_parse_partial(self):
        """A single-number string parses into just `major`, leaving
        `minor`/`patch` at their `None` defaults."""
        assert SemanticVersion.parse("2") == SemanticVersion(2)


class TestProductStringForm:
    """Converting a `Product` to and from its `name/version (comment)`
    string form."""

    def test_str_with_version(self):
        """A product with a version renders as `name/version`."""
        assert str(Product("HTTP", "1.1")) == "HTTP/1.1"

    def test_str_without_version(self):
        """A product with no version renders as just its name, with no
        trailing slash."""
        assert str(Product("Gossip")) == "Gossip"

    def test_str_with_comment(self):
        """A product with a comment appends it in parentheses after the
        name/version."""
        assert str(Product("Gossip", "0.0.1", "macOS")) == "Gossip/0.0.1 (macOS)"

    def test_parse_name_and_version(self):
        """Parsing a `name/version` string splits it into those two
        fields."""
        assert Product.parse("Gossip/0.0.1") == Product("Gossip", "0.0.1")

    def test_parse_name_only(self):
        """Parsing a bare name with no `/` leaves `version` as `None`."""
        assert Product.parse("Gossip") == Product("Gossip", None)

    def test_parse_with_comment(self):
        """Parsing a `name/version (comment)` string extracts all three
        fields, including a comment that contains its own spaces and
        punctuation."""
        product = Product.parse("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)")
        assert product.name == "Mozilla"
        assert product.version == "5.0"
        assert product.comment == "Macintosh; Intel Mac OS X 10_15"

    def test_parse_round_trips_str(self):
        """Parsing a product's string form and converting it back
        reproduces the original string."""
        original = "Gossip/0.0.1"
        assert str(Product.parse(original)) == original


class TestProductFactories:
    """The factories that describe this process's own environment, rather
    than parsing one from a string."""

    def test_gossip_factory_uses_installed_version(self):
        """`Product.gossip()` reports the installed package version, not a
        placeholder."""
        product = Product.gossip()
        assert product.name == "Gossip"
        assert product.version is not None

    def test_operating_system_factory_matches_platform_module(self):
        """`Product.operating_system()` reports the same system name and
        release that the stdlib `platform` module reports."""
        product = Product.operating_system()
        assert product.name == platform.system()
        assert product.version == platform.release()


class TestProductStackStringForm:
    """Converting a `ProductStack` to and from the space-separated string
    form used in headers like `User-Agent`."""

    def test_str_joins_products_with_spaces(self):
        """Multiple products join into one string, space-separated."""
        agent = stack(Product("Darwin", "24.6.0"), Product("UPnP", "2.0"))
        assert str(agent) == "Darwin/24.6.0 UPnP/2.0"

    def test_parse_splits_multiple_products(self):
        """A space-separated string parses back into one `Product` per
        entry."""
        parsed = ProductStack.parse("Darwin/24.6.0 UPnP/2.0 Gossip/0.0.1")
        assert parsed is not None
        assert parsed.products == (
            Product("Darwin", "24.6.0"),
            Product("UPnP", "2.0"),
            Product("Gossip", "0.0.1"),
        )

    def test_parse_keeps_comment_together_despite_internal_spaces(self):
        """A product's parenthesized comment isn't mistaken for a product
        boundary, even though the comment contains spaces of its own."""
        parsed = ProductStack.parse("Gossip/0.0.1 (built for macOS) UPnP/2.0")
        assert parsed is not None
        assert parsed.products == (
            Product("Gossip", "0.0.1", "built for macOS"),
            Product("UPnP", "2.0"),
        )

    def test_parse_handles_nested_parentheses_in_comment(self):
        """A comment containing its own nested parentheses parses as one
        whole comment, not truncated at the first closing paren."""
        parsed = ProductStack.parse("Product/1.0 (outer (inner) comment)")
        assert parsed is not None
        assert parsed.products == (Product("Product", "1.0", "outer (inner) comment"),)

    def test_parse_of_empty_string_yields_no_products(self):
        """An empty (or whitespace-only) string parses into a `ProductStack`
        with no products, rather than raising."""
        empty = ProductStack.parse("")
        blank = ProductStack.parse("   ")
        assert empty is not None
        assert blank is not None
        assert empty.products == ()
        assert blank.products == ()


class TestProductStackFactories:
    """`ProductStack.gossip()`, which builds the stack this process reports
    itself as."""

    def test_gossip_factory_includes_os_upnp_and_gossip(self):
        """`ProductStack.gossip()`'s last two entries are always the `UPnP`
        version and this package's own `Product`."""
        agent = ProductStack.gossip()
        names = tuple(product.name for product in agent.products)
        assert names[-2:] == ("UPnP", "Gossip")
