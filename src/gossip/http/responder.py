import logging
from datetime import datetime
from http import HTTPMethod, HTTPStatus
from ipaddress import ip_address
from typing import Any, Iterable, Mapping

from gossip.http.accessor import HTTPAccessor
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.mime import MediaType
from gossip.internet.product import ProductStack
from gossip.internet.uri import URI
from gossip.http.resource import ResourceCollection
from gossip.http.predicate import RequestPredicate
from gossip.network.endpoint import Endpoint
from gossip.network.serializer import Serializable

# See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Date
TIME_FORMAT = "%a, %d %b %Y %H:%M:%S GMT"
STAR_PATH = URI.parse("*")

log = logging.getLogger(__name__)


class HTTPResponder(ResourceCollection):
    """A responder to HTTP requests with appropriate HTTP responses.

    It manages all of the HTTP-specific parts of the responding-to-requests
    process, and can respond successfully or unsuccessfully to a request.

    It is also, itself, a `ResourceCollection` that can be used to respond to requests
    to the `*` path .
    """

    """The resources available on this server, keyed by their URI."""
    resources: Mapping[URI, ResourceCollection]

    """Loads the appropriate response from the resource, once identified."""
    accessor: HTTPAccessor

    """Static headers to include in all responses."""
    static_headers: dict[str, str]

    def __init__(
        self,
        resources: Mapping[URI, ResourceCollection],
        accessor: HTTPAccessor | None = None,
        static_headers: dict[str, str] | None = None,
        predicates: Mapping[str, RequestPredicate] | None = None,
    ):
        super().__init__(predicates)

        # Default headers for all responses includes the server information.
        if static_headers is None:
            static_headers = {}
        static_headers["Server"] = str(ProductStack.gossip())
        self.static_headers = static_headers

        # Our collection of resources includes this object as a root object, to
        # provide information about server capabilities.
        self.resources = {
            STAR_PATH: self,
            **resources,
        }

        if accessor is None:
            accessor = HTTPAccessor()
        self.accessor = accessor

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}, resources={self.resources}, data={self.data}>"

    def default_headers(self) -> dict[str, str]:
        """The standard headers for an HTTP response message from this server."""
        request_time = datetime.now()
        return self.static_headers | {
            "Date": request_time.strftime(TIME_FORMAT),
        }

    async def respond(self, request: HTTPRequest, remote_endpoint: Endpoint, local_endpoint: Endpoint) -> Iterable[Serializable]:
        """Identifies the targeted resource and gets the responder to handle it.

        Manages error-handling and walks through the resource-identifying step,
        the representation-checking step, and calling out to the responder to
        handle the request once that's done.
        """
        # Compile the full identifier, including a `Host` parameter if given.
        if not request.target.netloc:
            header_host = request.headers.get("Host", "")
            # SSDP sets the `Host` header to be the broadcast IP address, not a
            # hostname, so we'll check it's not an IP address first.
            try:
                ip_address(header_host)
                identifier = request.target._replace(netloc=header_host)
            except ValueError:
                identifier = request.target
        else:
            identifier = request.target

        try:
            # First, identify the resource the request is targeting.
            target = self.resources.get(identifier)
        except (ValueError, KeyError, FileNotFoundError) as e:
            # Errors during request parsing, informing the user the request was the problem.
            log.debug("Error during target identification: %s", identifier)
            responses = self.unidentifiable(e)
        else:
            if target is None:
                log.debug("No target found for target: %s", identifier)
                responses = self.unidentifiable()
            else:
                # Check if the resource can be represented according to the
                # request constraints.
                constraints = target.is_representable(request.headers)

                # A non-Falsey value for the predicate header means it can be represented.
                if constraints and not all(value for value, _ in constraints.values()):
                    # ResourceCollection found, but constraints not satisfiable.
                    log.debug("Unsatisfable request for %s (%s)", target, identifier)
                    responses = self.unsatisfiable(constraints)

                # We can now execute the function referenced by the method.
                return await self.successful(target, request, constraints, remote_endpoint, local_endpoint)

        # This might be a one-time iterable, so we'll generate a tuple of
        # responses so we can iterate over it multiple times.
        responses = tuple(responses)

        # We always want to send the response, even if an exception occurred.
        if responses:
            for response in responses:
                log.info("<- Responding to `%r` -> `%r`", request, response)
        else:
            log.debug("<- No response for `%r`", request)
        return responses

    def unidentifiable(self, error: Exception | None = None) -> Iterable[HTTPResponse]:
        """Returns a response for when no target resource can be identified."""
        match error:
            case ValueError():
                # The target URI is invalid
                status = HTTPStatus.BAD_REQUEST
            case KeyError():
                # The target URI was valid, but the domain was invalid
                status = HTTPStatus.MISDIRECTED_REQUEST
            case _:
                # No error, we just didn't find the target resource
                status = HTTPStatus.NOT_FOUND
        return (HTTPResponse(status, self.default_headers()),)

    def unsatisfiable(self, constraints: Mapping[str, tuple[Any, Mapping[str, str]]]) -> Iterable[HTTPResponse]:
        """Returns a response if a resource was found, but the request could not be satisfied."""
        # For a convenient error message, we'll dump the keys to the
        # constraints that weren't met.
        failures = {header for (header, _), value in constraints.items() if not value}
        if "Accept" in failures:
            status = HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        elif "Authorization" in failures:
            status = HTTPStatus.UNAUTHORIZED
        else:
            status = HTTPStatus.PRECONDITION_FAILED

        return (HTTPResponse(status, self.default_headers()),)

    def unknown_method(self) -> Iterable[HTTPResponse]:
        """Returns a response for any unknown methods."""
        return (HTTPResponse(HTTPStatus.METHOD_NOT_ALLOWED, self.default_headers()),)

    async def successful(self, target: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]]], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Generates successful responses for the given request and constraints.

        Any responses which need access to the entire request are handled here,
        resource-specific responses are handled by the resource via accessor and
        don't get access to the raw `HTTPRequest`.
        """
        match request.method:
            case HTTPMethod.CONNECT:
                # TODO: Implement this, I forget how connect works.
                return ()
            case HTTPMethod.TRACE:
                # Spit the request back to the client, as it was received.
                body = bytes(request)
                metadata = {
                    "Content-Type": str(MediaType.message("http")),
                    "Content-Length": str(len(body)),
                }
                response_headers = self.default_headers() | dict(metadata)
                return (HTTPResponse(HTTPStatus.OK, response_headers, body=body),)
            case _:
                if request.method not in self.accessor.methods:
                    return self.unknown_method()
                else:
                    return await self.accessor.access(target, request, constraints, self.default_headers(), remote, local)

    def subcollections(self) -> Mapping[URI, "ResourceCollection"]:
        """Return a mapping of all resource collections this responder contains."""
        return {uri: thing for uri, thing in self.resources.items() if uri != STAR_PATH}

    async def represent(self, exact_uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> tuple[Any, Mapping[str, str]]:
        # Star-path responses have no defined body or extra metadata,
        # subclasses can override.
        return (None, {})

    async def options(self, uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> Mapping[str, str]:
        """Returns key-value pairs describing how this responder communicates."""
        return {"Allow": ", ".join(self.accessor.methods.keys())}
