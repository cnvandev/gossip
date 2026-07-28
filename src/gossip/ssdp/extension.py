import logging
from collections.abc import Iterable, Mapping
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

    async def search(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], response_headers: Mapping[str, str], remote: Endpoint, local: Endpoint) -> Iterable[HTTPResponse]:
        """Create an appropriate response to a `SEARCH` request.

        The target resource for the request is always `*` according to the spec,
        so it will always be the `SSDPResponder`
        """
        # TODO: I would like to use the predicate system to filter subresources.
        # I think the `*` item is matching the resource correctly, but it should
        # be filtering subresources - maybe using the constraints.
        log.info("Remote: %s", remote)
        log.info("Local: %s", local)

        # ST header contains the search target
        search_target = URI.parse(request.headers.get("ST", ""))

        # We'll return a response for every matching resource in the collection.
        options = ((uri, target, metadata) for uri, subcollection in resource.subcollections().items() for target, metadata in subcollection.items() if all(subcollection.is_representable(request.headers)))
        matches = ((uri, target, metadata) for uri, target, metadata in options if ((target == search_target) or (search_target == SSDP_ALL)))

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
