import logging
from http import HTTPStatus
from typing import Any, Iterable, Mapping

from gossip.http.extension.constants import Scope
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.ssdp.uri import SSDPTarget

log = logging.getLogger(__name__)

SSDP_ALL = SSDPTarget.all()


class DiscoverExtension(Extension):

    def __init__(self):
        super().__init__(
            URI.ssdp("discover"),
            {"SEARCH": self.search.__get__(self)},
            scope=Scope.END_TO_END,
        )

    async def search(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], response_headers: Mapping[str, str]) -> Iterable[HTTPResponse]:
        """Handle an SSDP search request."""
        # ST header contains the search target
        search_target = URI.parse(request.headers.get("ST", ""))

        # We'll return a response for every matching resource in the collection.
        options = ((str(uri), target, metadata) for uri, subcollection in resource.subcollections().items() for target, metadata in subcollection.items() if all(subcollection.is_representable(request.headers)))
        matches = ((uri, target, metadata) for uri, target, metadata in options if ((target == search_target) or (search_target == SSDP_ALL)))

        # We'll build out the headers for each response.
        responses = (
            resource_headers
            | dict(response_headers)
            | {
                "ST": str(target),
                "Location": uri,
                "Cache-Control": "max-age=1800",
            }
            for uri, target, resource_headers in matches
        )
        responses = tuple(HTTPResponse(HTTPStatus.OK, sub) for sub in responses)
        return responses


DISCOVER = DiscoverExtension()
