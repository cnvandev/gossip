import logging
from collections.abc import Iterable, Mapping
from http import HTTPStatus
from typing import Any

from gossip.http.accessor import HTTPAccessor
from gossip.http.extension.constants import Scope, Strength
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.predicate import RequestPredicate
from gossip.http.resource import ResourceCollection
from gossip.http.responder import HTTPResponder
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint

log = logging.getLogger(__name__)


class ExtendedHTTPResponder(HTTPResponder):
    """An HTTP responder that supports HTTP message extensions.

    It manages known extensions and returns a 510 Not Extended for requests with
    unknown mandatory extensions.
    """

    extensions: Mapping[URI | str, Extension]

    def __init__(
        self,
        resources: Mapping[URI, ResourceCollection],
        extensions: Iterable[Extension] | None = None,
        accessor: HTTPAccessor | None = None,
        static_headers: dict[str, str] | None = None,
        predicates: Mapping[str, RequestPredicate] | None = None,
    ):
        super().__init__(resources, accessor, static_headers, predicates)
        if extensions is None:
            extensions = {}
        self.extensions = {extension.identifier: extension for extension in extensions}
        log.debug(f"Initializing with extensions: {tuple(map(str, self.extensions.keys()))}")

    async def options(self, uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> Mapping[str, str]:
        """Returns key-value pairs describing how this responder communicates."""
        accessor_methods = set(self.accessor.methods.keys())
        extension_methods = {method for extension in self.extensions.values() for method in extension.methods}
        allowed_methods = set(map(str.upper, accessor_methods | extension_methods))
        return {"Allow": ", ".join(allowed_methods)}

    async def successful(self, target: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]]], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Returns the successful response for the given request.

        Also does additional checks for the request to make sure it's requesting
        valid extensions, throwing a 510 Not Extended error if not.
        """
        # We'll check all combinations of strength & scope as there are only 4.
        has_mandatory = False
        for scope in Scope:
            for strength in Strength:
                header_key = "-".join(filter(None, (scope.value, strength.value)))
                # If the request has a declaration header for that combo, parse.
                if extension_value := request.headers.get(header_key, None):
                    # There could be multiple extensions, joined by a comma.
                    header_values = extension_value.split(",")
                    for value in header_values:
                        # Split into params & value, parse the namespace.
                        parts = value.strip().split(";")

                        # The first part is the URI/field name of the extension.
                        # RFC 2774: "A URI can unambiguously be distinguished
                        # from a field-name by the presence of a colon (":")."
                        # Otherwise, the declaration is a normal header key.
                        definition = parts[0].strip('"')
                        if ":" in definition:
                            definition = URI.parse(definition)

                        # If we don't know an extension indicated as mandatory,
                        # we throw a `510 Not Extended`.
                        if strength == Strength.MANDATORY and definition not in self.extensions:
                            log.debug(f"Unknown mandatory extension `{definition}`")
                            return (HTTPResponse(HTTPStatus.NOT_EXTENDED, self.default_headers()),)
                        else:
                            has_mandatory = True

        # Mandatory requests have an `M-` prefix, strip it to get the actual
        # method.
        if has_mandatory:
            request = HTTPRequest(
                request.method.lstrip("M-"),
                request.target,
                request.headers,
                request.body,
                request.protocol,
            )

        # Reply with the extension, if supported.
        for extension in self.extensions.values():
            if request.method in extension.methods:
                return await extension.access(target, request, constraints, self.default_headers(), remote, local)
                break
        else:
            return await super().successful(target, request, constraints, remote, local)
