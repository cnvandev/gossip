from typing import NamedTuple, Self, override


class MediaType(NamedTuple):
    """A media type: the top-level type and subtype pair that uniquely
    identifies a registered data format, independent of whatever protocol
    happens to be carrying it (an HTTP `Content-Type`/`Accept` header, a
    MIME email, or otherwise).

    Per RFC 6838 §4.2, "All registered media types MUST be assigned
    top-level type and subtype names. The combination of these names
    serves to uniquely identify the media type, and the subtype name
    facet (or the absence of one) identifies the registration tree."

    See: https://www.rfc-editor.org/rfc/rfc6838#section-4.2
    """

    type: str
    """The top-level media type (e.g. `text`, `image`, `application`).
    Per RFC 6838 §4.2, combined with `subtype` it "serves to uniquely
    identify the media type"."""

    subtype: str
    """The media subtype. Per RFC 6838 §4.2, "the subtype name facet (or
    the absence of one) identifies the registration tree" it was
    registered under (e.g. the standards tree, or a vendor's `vnd.`
    tree)."""

    @classmethod
    def parse(cls, string: str) -> Self:
        """Parses a string into a MediaType object."""
        return cls(*string.split("/"))

    @classmethod
    def all(cls) -> Self:
        """Returns a wildcard media type."""
        return cls("*", "*")

    @classmethod
    def application(cls, subtype: str) -> Self:
        """Returns an application media type."""
        return cls("application", subtype)

    @classmethod
    def image(cls, subtype: str) -> Self:
        """Returns an image media type."""
        return cls("image", subtype)

    @classmethod
    def message(cls, subtype: str) -> Self:
        """Returns a message media type."""
        return cls("message", subtype)

    @classmethod
    def text(cls, subtype: str) -> Self:
        """Returns an text media type."""
        return cls("text", subtype)

    @classmethod
    def video(cls, subtype: str) -> Self:
        """Returns an video media type."""
        return cls("video", subtype)

    def covers(self, other: tuple[str, ...]) -> bool:
        """True if `self` is an equal-or-more-general pattern that matches
        every representation `other` matches: every dimension where `self`
        is concrete agrees with `other`, and `self` is free to be wildcarded
        anywhere `other` is more specific. `text/*` covers `text/html`,
        `*/*` covers everything, and every media type covers itself.

        Media type specificity is a *partial* order, not a total one -
        `text/html` and `image/png` specialize different dimensions, so
        neither covers the other. This method is the single relation the
        rest of the comparison operators below are built from.
        """
        if not isinstance(other, MediaType):
            other = self.__class__(*other)
        type_matches = self.type == "*" or self.type == other.type
        subtype_matches = self.subtype == "*" or self.subtype == other.subtype
        return type_matches and subtype_matches

    @override
    def __le__(self, other: tuple[str, ...]) -> bool:
        """True if `other` covers `self`, i.e. `self` is at least as
        specific as `other` (`text/html <= text/*`, `text/html <= */*`,
        `text/html <= text/html`).
        """
        if not isinstance(other, MediaType):
            other = self.__class__(*other)
        return other.covers(self)

    @override
    def __ge__(self, other: tuple[str, ...]) -> bool:
        """True if `self` covers `other`, i.e. `self` is at least as
        general as `other`."""
        if not isinstance(other, MediaType):
            other = self.__class__(*other)
        return self.covers(other)

    @override
    def __lt__(self, other: tuple[str, ...]) -> bool:
        """True if `self` is strictly more specific than `other`: `other`
        covers `self`, but `self` doesn't cover `other` back."""
        return self <= other and not self >= other

    @override
    def __gt__(self, other: tuple[str, ...]) -> bool:
        """True if `self` is strictly more general than `other`."""
        return self >= other and not self <= other

    @override
    def __str__(self) -> str:
        """Returns a string that fully describes the media format."""
        return f"{self.type}/{self.subtype}"
