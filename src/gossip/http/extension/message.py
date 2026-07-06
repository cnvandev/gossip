from typing import Mapping

from gossip.http.extension.constants import Scope
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint


class ExtendedHTTPRequest:
    """An HTTP request that contains extensions."""

    @classmethod
    def for_url(cls, method: str, uri: URI, headers: Mapping[Extension | None, Mapping[str, str]] | None = None) -> tuple[HTTPRequest, Endpoint]:
        if headers is None:
            headers = dict()

        # Generate all the extended headers via their prefix.
        request_headers = {extension.extended_key(key) if extension is not None else key: value for extension, extension_headers in headers.items() for key, value in extension_headers.items()}

        # Collecting all the hop-by-hop extensions, and their headers.
        hop_by_hop_ex = set(e for e in headers.keys() if e is not None and e.scope == Scope.HOP_BY_HOP)
        hop_by_hop_headers = {extension.extended_key(key) for extension, extension_headers in headers.items() for key in extension_headers.keys() if extension is not None and extension.scope == Scope.HOP_BY_HOP}

        # If there are any hop-by-hop headers, we'll put them in the Connection header.
        connection = request_headers.pop("Connection", "")
        if connection:
            connection_headers = connection.split(",") + list(ex.declaration_key(method) for ex in hop_by_hop_ex) + list(hop_by_hop_headers)
            request_headers["Connection"] = ", ".join(connection_headers)

        return HTTPRequest.for_url(method, uri, request_headers)
