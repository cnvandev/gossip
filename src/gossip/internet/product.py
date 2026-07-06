"""Product and software stack strings."""

import platform
from importlib.metadata import version as module_version
from typing import NamedTuple, Self, override


class SemanticVersion(NamedTuple):
    """See: https://semver.org"""

    major: int | None
    minor: int | None = None
    patch: int | None = None

    @classmethod
    def parse(cls, string: str) -> Self:
        parts = map(int, string.split("."))
        return cls(*parts)


class Product(NamedTuple):
    """An identifier for a piece of software, with an optional version and
    comment, as defined in RFC 9110.
    """

    name: str
    version: str | None = None
    comment: str | None = None

    @override
    def __str__(self):
        """Returns a string representation of the identifier.

        Joins the name & version by a slash, and adds a comment in brackets
        (if present).
        """
        base = "/".join(filter(None, (self.name, self.version)))
        if self.comment is not None:
            base += f" ({self.comment})"
        return base

    def semver(self) -> SemanticVersion | None:
        return SemanticVersion.parse(self.version) if self.version else None

    @classmethod
    def operating_system(cls) -> Self:
        """Returns a Product for the current operating system."""
        return cls(platform.system(), platform.release())

    @classmethod
    def gossip(cls) -> Self:
        """Returns a Product for the current Gossip version."""
        gossip_version = module_version("gossip")
        return cls("Gossip", gossip_version)

    @classmethod
    def parse(cls, string: str) -> Self:
        """Parses a string into a Product."""
        trimmed = string.strip()
        # These strings can have an optional comment in parentheses, and an
        # optional version after a slash, following the name.
        if " " in trimmed:
            product, comment = trimmed.strip().split(None, 1)
            comment = comment.strip("()")
        else:
            product, comment = trimmed.strip(), None

        if "/" in product:
            name, version = product.split("/", 1)
        else:
            name, version = product, None
        return cls(name, version, comment)


class ProductStack(NamedTuple):
    """A software stack identified by one or more product identifiers."""

    products: tuple[Product, ...]

    @override
    def __str__(self):
        """Returns a string representation of the agent, suitable for a header."""
        return " ".join((str(product) for product in self.products))

    @classmethod
    def gossip(cls):
        """Returns an Agent string for the current OS & Gossip version."""
        return stack(
            Product.operating_system(),
            Product("UPnP", "2.0"),
            Product.gossip(),
        )

    @classmethod
    def parse(cls, string: str) -> Self | None:
        """Parses a string into an `ProductStack`, or `None` if it's mal-formed."""
        # Simple parser, we split on whitespace unless we're in a comment state.
        products: list[Product] = []
        token = ""
        comment = False
        last_space = False
        for character in string.strip():
            if character == "(":
                # We're starting a comment (or nesting further),
                # nothing to do yet.
                if not comment:
                    token += " ("
                else:
                    token += character
                comment += 1
                last_space = False
            elif character == ")":
                # The comment is over (or reducing nesting), we can parse the
                # token after the next space.
                if comment == 1:
                    token += ")"
                else:
                    token += character
                comment -= 1
                last_space = False
            elif not character.isspace() or comment:
                # It's a regular character, or a space and we're in a comment.
                # If the last character was a space, we're starting a new token.
                if last_space:
                    products.append(Product.parse(token))
                    token = ""
                    last_space = False
                # In any case, we're adding the character to the next token.
                token += character
            else:
                # It's a space and we're not in a comment, if the next character
                # is `(` we start the comment, otherwise it's a new token.
                last_space = True

        if token:
            products.append(Product.parse(token))

        return cls(tuple(products))


def stack(*products: Product) -> ProductStack:
    """A factory for creating `ProductStack` instances from a sequence of
    `Products`."""
    return ProductStack(products=products)
