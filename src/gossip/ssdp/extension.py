import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from gossip.http.extension.constants import Scope
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.ssdp.uri import SSDPTarget

log = logging.getLogger(__name__)

SSDP_ALL = SSDPTarget.all()


class DiscoverExtension(Extension):
    """The `ssdp:discover` extension, powering search requests for SSDP."""

    def __init__(self):
        super().__init__(
            URI.ssdp("discover"),
            {"SEARCH": self.search.__get__(self)},
            scope=Scope.END_TO_END,
        )

    async def search(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], response_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> tuple[HTTPResponse, ...]:
        """Create an appropriate response to a `SEARCH` request.

        The target resource for the request is always `*` according to the spec,
        so it will always be the `SSDPResponder`
        """
        # TODO: I would like to use the predicate system to filter subresources.
        # I think the `*` item is matching the resource correctly, but it should
        # be filtering subresources - maybe using the constraints.
        log.info("Remote: %s", remote)
        log.info("Local: %s", local)

        # ST header contains the search target - parsed just to confirm it's a
        # well-formed URI, matched below as a string against `target` (itself
        # a string, not a parsed URI).
        search_target = URI.parse(request.headers.get("ST", ""))
        string_target = str(search_target)

        # We'll return a response for every matching resource in the collection.
        # Every predicate's result is now an (option, args) pair even on
        # rejection (option is `None`), so `.values()` is never falsy on its
        # own - checking the option itself is what tells satisfiability apart.
        options = ((uri, target, metadata) for uri, subcollection in resource.subcollections().items() for target, metadata in subcollection.items() if all(value for value, _ in subcollection.is_representable(request.headers).values()))
        matches = ((uri, target, metadata) for uri, target, metadata in options if ((search_target == SSDP_ALL) or (target == string_target)))

        # We'll build out the headers for each response.
        responses = (
            resource_headers
            | dict(response_headers)
            | {
                "ST": str(target),
                "Location": URI(scheme="http", netloc=str(local), path=uri.path, query=uri.query, params=uri.params, fragment=uri.fragment),
                "Cache-Control": "max-age=1800",
            }
            for uri, target, resource_headers in matches
        )
        responses = tuple(HTTPResponse(HTTPStatus.OK, sub) for sub in responses)
        return responses


DISCOVER = DiscoverExtension()
