import logging
from http import HTTPStatus
from typing import Any, Iterable, Mapping

from gossip.http.extension.constants import Scope, Strength
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.ssdp.headers import BOOT_ID, CONFIG_ID, CPFN
from gossip.ssdp.uri import SSDPTarget, UniqueServiceName

log = logging.getLogger(__name__)

SSDP_ALL = SSDPTarget.all()


async def search(resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], response_headers: Mapping[str, str]) -> Iterable[HTTPResponse]:
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


# The `ssdp:discover` extension requires the following headers in request
# messages:
BROADCAST_DISCOVER = Extension(
    URI.ssdp("discover"),
    {
        "SEARCH": {
            Strength.MANDATORY: {
                "Host": str,  # the host to send the request to
                "ST": SSDPTarget.parse,  # the service type to discover
                "MX": int,  # the maximum wait time in seconds
            },
            Strength.OPTIONAL: {
                "NLS": str,
                str(CPFN): str,  # the friendly name of the control point
            },
        },
        "NOTIFY": {
            Strength.MANDATORY: {
                "Host": str,
                "NT": SSDPTarget.parse,  # The notification target
                "NTS": URI.parse,  # The notification subtype: `ssdp:alive`, `ssdp:update`, or `ssdp:byebye`.
                "USN": UniqueServiceName.parse,  # The USN of the notifier
                str(BOOT_ID): str,
                str(CONFIG_ID): str,
            },
            Strength.OPTIONAL: {
                "NLS": str,
            },
        },
    },
    {"SEARCH": search},
    scope=Scope.END_TO_END,
)

UNICAST_DISCOVER = Extension(
    URI.ssdp("discover"),
    {
        "SEARCH": {
            Strength.MANDATORY: {
                "Host": str,  # the host to send the request to
                "ST": SSDPTarget.parse,  # the service type to discover
            },
            Strength.OPTIONAL: {
                "NLS": str,
                str(CPFN): str,  # the friendly name of the control point
            },
        },
        "NOTIFY": {
            Strength.MANDATORY: {
                "Host": str,
                "NT": SSDPTarget.parse,  # The notification target
                "NTS": URI.parse,  # The notification subtype: `ssdp:alive`, `ssdp:update`, or `ssdp:byebye`.
                "USN": UniqueServiceName.parse,  # The USN of the notifier
                str(BOOT_ID): str,
                str(CONFIG_ID): str,
            },
            Strength.OPTIONAL: {
                "NLS": str,
            },
        },
    },
    scope=Scope.END_TO_END,
)
