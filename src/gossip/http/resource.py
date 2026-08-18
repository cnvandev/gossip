import logging
from asyncio import Future, get_running_loop
from asyncio.streams import StreamReader
from collections import UserDict
from collections.abc import Buffer, Mapping
from typing import Any, Self

from gossip.http.predicate import RequestPredicate
from gossip.internet.uri import URI
from gossip.network.serializer import BoundedReader
from gossip.utils.multidict import multidict

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class Resource:
    """A representation of the specific resource carried by an HTTP
    message: the URL identifying it, its headers, a readable body, and
    trailers - ready for async reading.

    `body` is always a `BoundedReader`; read it directly for streaming
    access, or call `read_body()` to materialize the whole thing into a
    `Buffer`. `trailers` is a `Future` that resolves once `body`'s pump
    finishes; `await` it (or add a done callback) rather than reading it
    synchronously.

    Whether `body` is actually bounded is exactly `Content-Length`'s
    presence: a valid header makes this standards-compliant - `body` cuts
    off at exactly that many bytes, and `trailers` resolves to empty the
    moment it does, regardless of who's reading `body`, and regardless of
    whatever `trailers` value was passed in above. That's not a
    simplification; `Content-Length` and trailers are mutually exclusive
    in HTTP (RFC 9112 §6.3), so a Content-Length-bounded body provably has
    none. Without a valid `Content-Length`, `body` pumps until the given
    reader ends on its own (unbounded - trusting the source to end by
    closing), and `trailers` resolves to the value passed in above once
    it does.

    Requires a running event loop to construct: `trailers` is a real
    `Future` bound to one from the start, and `body`'s `BoundedReader`
    starts its pump task immediately.
    """

    identifier: URI
    headers: multidict
    body: StreamReader
    trailers: Future[multidict]

    def __init__(self, identifier: URI, headers: Mapping[str, str], body: StreamReader, trailers: Mapping[str, str] | None = None):
        self.identifier = identifier
        self.headers = multidict(headers)
        self.trailers = get_running_loop().create_future()

        content_length_str = self.headers.get("Content-Length")
        content_length = None
        if content_length_str is not None:
            try:
                content_length = int(content_length_str)
            except ValueError:
                content_length = None

        # Content-Length's presence or absence is exactly the
        # standards-compliant signal for whether trailers can exist at
        # all (RFC 9112 §6.3) - present, there's provably none regardless
        # of what was passed in as `trailers` above; absent, whatever was
        # passed in is what `trailers` eventually resolves to.
        self._pending_trailers = multidict() if content_length is not None else multidict(trailers or {})
        self.body = BoundedReader(body, content_length, on_exhausted=self._resolve_trailers)

    def _resolve_trailers(self) -> None:
        if not self.trailers.done():
            self.trailers.set_result(self._pending_trailers)

    async def read_body(self) -> Buffer | None:
        """Materializes this resource's body into a `Buffer` by reading
        `body` until EOF - bounded or not, `trailers` resolves on its own
        once `body`'s pump finishes, whether or not this was what
        triggered it.

        For a `Content-Length`-bounded `body`, that's the right call for a
        caller that wants the whole thing as one `Buffer` and can wait for
        it. A caller that can't - one that wants to pump a live, unbounded
        body straight through as it arrives (e.g. an audio stream to
        speakers), in batches, via its own streaming parser - should read
        `self.body` directly instead of going through `read_body()`.
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

    def is_representable(self, request_headers: Mapping[str, str]) -> dict[str, tuple[Any, dict[str, str]]]:
        """Returns the output of each predicate against the request headers."""
        return {header: next(iter(predicate.accepts(request_headers.get(header, ""))), None) for header, predicate in self.predicates.items() if header in request_headers}

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
