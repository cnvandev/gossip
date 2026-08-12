import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from gossip.http.accessor import HTTPAccessor
from gossip.http.extension.constants import Scope, Strength
from gossip.http.field import parse_field_values
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint

log = logging.getLogger(__name__)


class Extension(HTTPAccessor):
    """An extension to support additional features for accessing HTTP resources.

    It's an `HTTPAccessor` so any identified resources can be accessed via its
    methods. It's designed so that subclasses will be able to subclass it and
    treat the requests differently (although the framework was never adopted
    outside of SSDP.)
    """

    identifier: URI | str
    scope: Scope

    def __init__(
        self,
        identifier: URI | str,
        methods: Mapping[str, Callable[[ResourceCollection, URI, Mapping[str, tuple[Any, Mapping[str, str]] | None], Mapping[str, str], Endpoint, Endpoint], Awaitable[Iterable[HTTPResponse]]]] | None = None,
        scope: Scope = Scope.END_TO_END,
    ):
        super().__init__(methods)
        self.identifier = identifier
        self.scope = scope

    def headers(self, request: HTTPRequest) -> Mapping[str, str]:
        """Returns this extension's own headers from `request`, stripped of
        their namespace prefix.

        Per RFC 2774, a request declares an extension (in a
        `Man`/`Opt`/`C-Man`/`C-Opt` header) along with the `ns=` namespace
        prefix its headers use. If this extension isn't declared, or is
        declared with no `ns=` given, there's no way to tell which headers
        (if any) belong to it, so none are returned.
        """
        namespace = None
        for strength in Strength:
            declaration_key = "-".join(filter(None, (self.scope, strength)))
            declaration_header = request.headers.get(declaration_key)
            if declaration_header is None:
                continue

            # The request has a declaration that might contain this extension.
            for declaration, params in parse_field_values(declaration_header):
                # The declaration itself is the URI/field name of the
                # extension. RFC 2774: "A URI can unambiguously be
                # distinguished from a field-name by the presence of a colon
                # (":")." Otherwise, the declaration is a normal header key.
                definition = declaration.strip('"')
                if ":" in definition:
                    definition = URI.parse(definition)

                if definition == self.identifier:
                    # This is us, we'll use our namespace.
                    namespace = params.get("ns") or None

        if namespace is None:
            return {}

        # Just return the headers that apply.
        return {key[2:]: value for key, value in request.headers.items() if key.startswith(namespace)}

    async def access(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        # Successful extension usage puts in this header, to indicate an
        # extension was used successfully.
        headers = dict(headers) | {"Ext": ""}
        return await super().access(resource, request, constraints, headers, remote, local)
