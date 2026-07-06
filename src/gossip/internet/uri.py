import logging
from typing import Self, override
from urllib.parse import ParseResult, urljoin, urlparse
from uuid import UUID

log = logging.getLogger(__name__)


class URI(ParseResult):
    """A more class-like URI while still using `urllib` for parsing."""

    @override
    def __str__(self) -> str:
        """Serialize the URI to a string using `urllib.parse.urlunparse`."""
        return self.geturl()

    def join(self, path: str) -> Self:
        new_path = urljoin(self.path, path)
        return self.__class__(self.scheme, self.netloc, new_path, self.params, self.query, self.fragment)

    @classmethod
    def parse(cls, url: str, scheme: str = "") -> Self:
        """Parse a URI from a string using `urllib.parse.urlparse`."""
        result = urlparse(url, scheme=scheme) if scheme else urlparse(url)
        return cls(*result._asdict().values())

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
