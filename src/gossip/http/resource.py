import logging
from collections import UserDict
from collections.abc import Buffer
from typing import Any, Mapping

from gossip.http.predicate import RequestPredicate
from gossip.internet.uri import URI

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class ResourceCollection(UserDict[str, dict[str, str]]):
    """A collection of resources under a top-level Uniform Resource Identifier.

    A resource is anything identifiable via Uniform Resource Identifier
    (URI), this collects resource accessed with similar methods and using a
    common set of predicates. Each Resource contained within this collection can
    be accessed via its path under the mapping interface (i.e. via `.get()`, or
    iterated over via `.items()`).

    Mainly renders the representation & checks if request matches this resource.
    It is a also a `Mapping` of `str` to `dict[str, str]`, as the resource is
    intended to wrap multiple representations with their own parameters. Think
    of it like the root node in a path tree with multiple files, or a way to
    access rows in a table in a database via UUID.

    Collections of resources are also "resources" themselves, so this also
    provides an interface for accessing subresources that might have different
    URLs entirely.
    """

    predicates: Mapping[str, RequestPredicate]

    def __init__(self, predicates: Mapping[str, RequestPredicate] | None = None, data: dict[str, dict[str, str]] | None = None):
        if predicates is None:
            predicates = dict()

        self.predicates = predicates
        super().__init__(data)

    def is_representable(self, request_headers: Mapping[str, str]) -> dict[str, tuple[Any, dict[str, str]]]:
        """Returns the output of each predicate against the request headers."""
        return {header: next(iter(predicate.accepts(request_headers.get(header, ""))), None) for header, predicate in self.predicates.items() if header in request_headers}

    def subcollections(self) -> Mapping[URI, "ResourceCollection"]:
        """Return a mapping of collections in this resource, if any.

        The default implementation returns an empty dictionary.
        """
        return {}

    async def options(self, uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> Mapping[str, str]:
        """Return the different representation options for this resource."""
        raise NotImplementedError("ResourceCollection subclasses need to implement options()")

    async def represent(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> tuple[Any, Mapping[str, str]]:
        """Respond to a request for the exact under the requested constraints."""
        # Something to conform the object to the constraints.
        raise NotImplementedError("ResourceCollection subclasses need to implement represent()")

    async def write(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], request_body: Buffer | None) -> tuple[Any, Mapping[str, str]]:
        """Write the body of the request to the resource."""
        raise NotImplementedError("ResourceCollection subclasses need to implement write()")

    async def delete(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> tuple[Any, Mapping[str, str]]:
        """Delete the resource's data so it will no longer be retrievable."""
        raise NotImplementedError("ResourceCollection subclasses need to implement delete()")

    async def patch(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], patch: Buffer | None) -> tuple[Any, Mapping[str, str]]:
        """Update a section of the resource's data."""
        raise NotImplementedError("ResourceCollection does not support patch()")
