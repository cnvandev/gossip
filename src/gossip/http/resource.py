import logging
from asyncio.streams import StreamReader
from collections import UserDict
from collections.abc import Buffer, Mapping
from typing import Any, Self

from gossip.http.predicate import RequestPredicate
from gossip.internet.uri import URI
from gossip.utils.multidict import multidict

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class Resource:
    """A representation of the specific resource carried by an HTTP
    message: the URL identifying it, its headers, and a readable body.

    `body` is used exactly as given - unbounded, with no `Content-Length`
    cutoff applied here (that used to come from wrapping it in a
    `BoundedReader`, which this class no longer does).
    """

    identifier: URI
    headers: multidict
    body: StreamReader

    def __init__(self, identifier: URI, headers: Mapping[str, str], body: StreamReader):
        self.identifier = identifier
        self.headers = multidict(headers)
        self.body = body

    async def read_body(self) -> Buffer | None:
        """Materializes this resource's body into a `Buffer` by reading
        `body` until EOF.

        A caller that wants to pump a live body straight through as it
        arrives (e.g. an audio stream to speakers), in batches, via its
        own streaming parser, should read `self.body` directly instead of
        going through `read_body()`.
        """
        return await self.body.read()


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
            predicates = {}

        self.predicates = predicates
        super().__init__(data)

    def is_representable(self, request_headers: Mapping[str, str]) -> dict[str, tuple[Any, Mapping[str, str]]]:
        """Returns the output of each predicate against the request headers.

        Each value is a tuple of (result, params) where result is some chosen
        representation option and params is a dict of representation parameters
        (i.e. codec settings, etc.) If the predicate rejects the request,
        the option is `False`y.
        """
        return {header: next(iter(predicate.accepts(request_headers.get(header, ""))), (None, {})) for header, predicate in self.predicates.items() if header in request_headers}

    def subcollections(self) -> Mapping[URI, Self]:
        """Return a mapping of collections in this resource, if any.

        The default implementation returns an empty dictionary.
        """
        return {}

    async def options(self, uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> Mapping[str, str]:
        """Return the different representation options for this resource."""
        raise NotImplementedError("ResourceCollection subclasses need to implement options()")

    async def represent(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> tuple[StreamReader | None, Mapping[str, str]]:
        """Respond to a request for the exact under the requested constraints."""
        # Something to conform the object to the constraints.
        raise NotImplementedError("ResourceCollection subclasses need to implement represent()")

    async def write(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], request_body: StreamReader | None) -> tuple[StreamReader | None, Mapping[str, str]]:
        """Write the body of the request to the resource."""
        raise NotImplementedError("ResourceCollection subclasses need to implement write()")

    async def delete(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> tuple[StreamReader | None, Mapping[str, str]]:
        """Delete the resource's data so it will no longer be retrievable."""
        raise NotImplementedError("ResourceCollection subclasses need to implement delete()")

    async def patch(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], patch: StreamReader | None) -> tuple[StreamReader | None, Mapping[str, str]]:
        """Update a section of the resource's data."""
        raise NotImplementedError("ResourceCollection does not support patch()")
