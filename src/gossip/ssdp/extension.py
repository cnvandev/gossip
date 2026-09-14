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

log = logging.getLogger(__name__)


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
        log.info("Remote: %s", remote)
        log.info("Local: %s", local)

        search_header = request.headers.get("ST", "")

        # A subcollection's own predicates (its `ST` predicate included -
        # see `SSDPTargetPredicate`) decide whether it's representable here
        # at all. Every predicate's result is an (option, args) pair even on
        # rejection (option is `None`), so `.values()` is never falsy on its
        # own - checking the option itself is what tells satisfiability apart.
        representable = ((uri, subcollection) for uri, subcollection in resource.subcollections().items() if all(value for value, _ in subcollection.is_representable(request.headers).values()))

        # `.accepts()` returns every target that satisfies the search (not
        # just the best one), so we reuse the subcollection's own `ST`
        # predicate to enumerate matching targets instead of comparing them
        # by hand.
        matches = ((uri, target, subcollection[str(target)]) for uri, subcollection in representable for target, _ in subcollection.predicates["ST"].accepts(search_header))

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
