from typing import Self, override
from urllib.parse import ParseResult, urljoin, urlparse
from uuid import UUID


class URI(ParseResult):
    """A more class-like URI while still using `urllib` for parsing."""

    @override
    def __str__(self) -> str:
        """Serialize the URI to a string using `urllib.parse.urlunparse`."""
        return self.geturl()

    def covers(self, other: tuple[str, ...]) -> bool:
        """True if `self` matches every request that `other` would.

        The base case is exact equality, with one wildcard: a bare `URI`
        (no scheme) whose `path` is exactly `*` covers every URI,
        regardless of scheme, domain, or `other`'s own path.

        A subclass may recognize additional patterns of its own.
        """
        if not isinstance(other, URI):
            other = self.__class__(*other)
        return (self == other) or (self.path == "*" and not self.scheme)

    @override
    def __le__(self, other: tuple[str, ...]) -> bool:
        """True if `other` covers `self`."""
        if not isinstance(other, URI):
            other = self.__class__(*other)
        return other.covers(self)

    @override
    def __ge__(self, other: tuple[str, ...]) -> bool:
        """True if `self` covers `other`."""
        if not isinstance(other, URI):
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

    def join(self, path: str) -> Self:
        """Resolve `path` against this URI as a relative reference (RFC
        3986 §5). If `path` is itself an absolute URI, it replaces this one
        entirely rather than being appended to it, the same as
        `urllib.parse.urljoin`."""
        return self.parse(urljoin(str(self), path))

    @classmethod
    def parse(cls, url: str, scheme: str = "") -> Self:
        """Parse a URI from a string using `urllib.parse.urlparse`."""
        return cls(*urlparse(url, scheme=scheme))

    @classmethod
    def http(cls, path: str) -> Self:
        return cls.parse(path, scheme="http")

    @classmethod
    def ssdp(cls, path: str) -> Self:
        return cls.parse(path, scheme="ssdp")

    @classmethod
    def upnp(cls, path: str) -> Self:
        return cls.parse(path, scheme="upnp")

    @classmethod
    def urn(cls, path: str) -> Self:
        return cls.parse(f"urn:{path}", scheme="urn")

    @classmethod
    def uuid(cls, uuid: UUID) -> Self:
        return cls.parse(str(uuid), scheme="uuid")
