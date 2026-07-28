import logging
from http import HTTPMethod, HTTPStatus
from typing import Any, Awaitable, Callable, Iterable, Mapping

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.resource import ResourceCollection
from gossip.network.endpoint import Endpoint

log = logging.getLogger(__name__)


class HTTPAccessor:
    """Makes method-specific responses requests for identified resource.

    The `HTTPResponder` can respond to any request in general, this class
    handles requests whose resources were correctly identified to a resource.
    """

    methods: Mapping[str, Callable[[ResourceCollection, HTTPRequest, Mapping[str, tuple[Any, Mapping[str, str]] | None], Mapping[str, str], Endpoint, Endpoint], Awaitable[Iterable[HTTPResponse]]]]

    def __init__(self, methods: Mapping[str, Callable[[ResourceCollection, HTTPRequest, Mapping[str, tuple[Any, Mapping[str, str]] | None], Mapping[str, str], Endpoint, Endpoint], Awaitable[Iterable[HTTPResponse]]]] | None = None):
        self.methods = dict(methods or dict()) | {
            HTTPMethod.GET: self.get,
            HTTPMethod.PUT: self.put,
            HTTPMethod.PATCH: self.patch,
            HTTPMethod.DELETE: self.delete,
            HTTPMethod.HEAD: self.head,
            HTTPMethod.OPTIONS: self.options,
        }

    async def access(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns a response for a successfully-targeted request.

        Assumes the caller has already validated the request method.
        Callers: do that.
        """
        log.debug("Target resource: %s", resource)
        if constraints:
            log.debug("Constraints: %s", constraints)
        caller = self.methods[request.method]
        return await caller(resource, request, constraints, headers, remote, local)

    async def options(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], static_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns a response for a request for the `OPTIONS` method."""
        option_headers = await resource.options(request.target, constraints)
        return (HTTPResponse(HTTPStatus.OK, dict(option_headers) | dict(static_headers)),)

    async def head(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], static_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns a response for the `HEAD` method."""
        _, metadata = await resource.represent(request.target, constraints)
        return (HTTPResponse(HTTPStatus.OK, dict(metadata) | dict(static_headers)),)

    async def get(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], static_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns a response for the `GET` method."""
        body, metadata = await resource.represent(request.target, constraints)
        return (HTTPResponse(HTTPStatus.OK, dict(metadata) | dict(static_headers), body),)

    async def put(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], static_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns a response for the `PUT` method."""
        response_body, metadata = await resource.write(request.target, constraints, request.body)
        return (HTTPResponse(HTTPStatus.OK, dict(metadata) | dict(static_headers), response_body),)

    async def patch(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], static_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns a response for the `PATCH` method."""
        body, metadata = await resource.patch(request.target, constraints, request.body)
        return (HTTPResponse(HTTPStatus.OK, dict(metadata) | dict(static_headers), body),)

    async def delete(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], static_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns a response for the `DELETE` method."""
        body, metadata = await resource.delete(request.target, constraints)
        return (HTTPResponse(HTTPStatus.NO_CONTENT, dict(metadata) | dict(static_headers), body),)
