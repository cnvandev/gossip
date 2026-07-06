import logging
from functools import total_ordering
from typing import NamedTuple, Self, override

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


@total_ordering
class MediaType(NamedTuple):
    """A media type specification, also known as a MIME type."""

    type: str
    subtype: str

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

    @override
    def __gt__(self, other: tuple[str, ...]):
        if not isinstance(other, MediaType):
            other = self.__class__(*other)
        larger_type = (self.type == "*") and (other.type != "*")
        larger_subtype = (self.type == other.type) and (self.subtype == "*") and (other.subtype != "*")
        value = larger_type ^ larger_subtype
        log.debug(f"__gt__ {self.type} > {other.type}, {larger_type} and {self.subtype} > {other.subtype}, {larger_subtype}, all: {value}")
        return value

    @override
    def __ge__(self, other: tuple[str, ...]):
        if not isinstance(other, MediaType):
            other = self.__class__(*other)
        larger_type = (self.type == "*") and (other.type != "*")
        larger_subtype = (self.type == other.type) and (self.subtype == "*") and (other.subtype != "*")
        value = larger_type or larger_subtype
        log.debug(f"__ge__ {self.type} > {other.type}, {larger_type} and {self.subtype} > {other.subtype}, {larger_subtype}, all: {value}")
        return value

    @override
    def __lt__(self, other: tuple[str, ...]):
        if not isinstance(other, MediaType):
            other = self.__class__(*other)
        smaller_type = (self.type != "*") and (other.type == "*")
        smaller_subtype = (self.type == other.type) and (self.subtype != "*") and (other.subtype == "*")
        value = smaller_type ^ smaller_subtype
        log.debug(f"__lt__ {self.type} < {other.type}, {smaller_type} and {self.subtype} < {other.subtype}, {smaller_subtype}, all: {value}")
        return value

    @override
    def __le__(self, other: tuple[str, ...]):
        if not isinstance(other, MediaType):
            other = self.__class__(*other)
        smaller_type = (self.type != "*") and (other.type == "*")
        smaller_subtype = (self.type == other.type) and (self.subtype != "*") and (other.subtype == "*")
        same = (self.type == other.type) and (self.subtype == other.subtype)
        value = smaller_type or smaller_subtype or same
        log.debug(f"__le__ {self.type} < {other.type}, {smaller_type} and {self.subtype} < {other.subtype}, {smaller_subtype}, all: {value}")
        return value

    @override
    def __str__(self) -> str:
        """Returns a string that fully describes the media format."""
        return "/".join((self.type, self.subtype))
