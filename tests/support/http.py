"""Shared HTTP test doubles and helpers.

Not a test module - imported by tests that need to verify what an
HTTPRequest actually carried, from the response it produced.
"""

from http import HTTPStatus

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.network.endpoint import Endpoint


async def echo_request(request: HTTPRequest, _remote: Endpoint, _local: Endpoint) -> tuple[HTTPResponse]:
    """A `Replier` callback that echoes the request's own method,
    target, and headers back as `Test-Request-*` response headers, so a
    test can assert on what the server actually received just by
    reading the response - no separate captured state needed."""
    headers = {
        "Test-Request-Method": request.method,
        "Test-Request-Target": str(request.target),
    }
    headers.update({f"Test-Request-{name}": value for name, value in request.headers.items()})
    return (HTTPResponse(HTTPStatus.OK, headers),)
