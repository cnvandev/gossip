import logging
from collections import defaultdict
from typing import Iterable

from langcodes import Language

from gossip.internet.mime import MediaType

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class RequestPredicate[T]:
    """A predicate to evaluate a few options, ranked by a quality parameter.

    If the predicate's `.accepts()` method returns a non-False-y value, the
    request can be satisfied according to the predicate's requirements.
    """

    # The set of options that this predicate compares its requirements against.
    options: list[T]

    def __init__(self, options: Iterable[T]):
        self.options = list(options)

    def parse(self, input: str) -> T:
        raise NotImplementedError("RequestPredicate subclass must implement compare() and parse().")

    def compare(self, option: T, acceptable: T) -> bool:
        raise NotImplementedError("RequestPredicate subclass must implement compare() and parse().")

    def accepts(self, accept_string: str) -> tuple[tuple[T, dict[str, str]], ...]:
        """Return a tuple of all acceptable options in our list (with args).

        Quality-ranked header matching algorithm: split on commas, parse, and
        return a tuple of all passing values. The first tuple is the highest
        quality match.

        If none are acceptable, it returns an empty tuple.
        """
        types_args = (option.strip().split(";") for option in accept_string.split(","))
        acceptable = ((self.parse(type_string), dict(pair.strip().split("=") for pair in args)) for type_string, *args in types_args)

        # We'll group the acceptable types by quality according to the accept headers.
        grouped: defaultdict[float, list[tuple[T, dict[str, str]]]] = defaultdict(list)
        for accept_type, args in acceptable:
            # 1 is the default quality, as per RFC <whatever>
            quality = float(args.pop("q", 1))
            grouped[quality].append((accept_type, args))
        log.debug("Grouped: %s", dict(grouped))

        # Now go down the list and return the first group with any acceptable
        # options for our .
        log.debug("Options: %s", self.options)
        for quality in sorted(grouped.keys(), reverse=True):
            accepted = tuple((option, args) for option in self.options for (acceptable, args) in grouped[quality] if self.compare(option, acceptable))
            log.debug("Accepted: %s", accepted)
            if accepted:
                return accepted

        # If we're here, we found nothing.
        return tuple()


class MediaTypePredicate(RequestPredicate[MediaType]):
    """A predicate for comparing media types.

    This predicate is used to compare media types via the `MediaType` class (see
    it for more details on parsing). The comparison allows whichever of our
    media types are a subset of the acceptable media types, sorted by quality.
    """

    def parse(self, input: str) -> MediaType:
        return MediaType.parse(input)

    def compare(self, option: MediaType, acceptable: MediaType):
        log.debug("Comparing %s and %s", option, acceptable)
        return option <= acceptable


class LanguagePredicate(RequestPredicate[Language]):
    """A predicate for comparing languages.

    This predicate uses the `Language` class from the `langcodes` library to
    parse the language code, and it compares the distance between the
    representable options and the acceptable types.
    """

    MIN_DISTANCE = 25

    def parse(self, input: str) -> Language:
        return Language.get(input)

    def compare(self, option: Language, acceptable: Language):
        return option.distance(acceptable) < self.MIN_DISTANCE


class StringPredicate(RequestPredicate[str]):
    """A predicate for comparing strings.

    This predicate is used to compare strings for equality. It is a simple
    predicate that can be used to match against a list of options.
    """

    def parse(self, input: str):
        return input

    def compare(self, option: str, acceptable: str):
        return option == acceptable
