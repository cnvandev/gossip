import logging
from collections.abc import Iterable, Mapping
from typing import Any

from gossip.http.accessor import HTTPAccessor
from gossip.http.extension.framework import Extension
from gossip.http.extension.responder import ExtendedHTTPResponder
from gossip.http.message import HTTPResponse
from gossip.http.resource import ResourceCollection
from gossip.internet.uri import URI

log = logging.getLogger(__name__)


class SSDPResponder(ExtendedHTTPResponder):
    """A special type of HTTP responder that doesn't send error replies.

    RFC 2774 specifies no responses are given for i.e. 404s or authentication
    failures. Since they're broadcast on the network, we avoid clogging up the
    network with error responses.
    """

    def __init__(
        self,
        resources: Mapping[URI, ResourceCollection],
        extensions: Iterable[Extension] | None = None,
        accessor: HTTPAccessor | None = None,
        static_headers: dict[str, str] | None = None,
    ):
        super().__init__(resources, extensions, accessor, static_headers)

    def unidentifiable(self, error: Exception | None = None) -> Iterable[HTTPResponse]:
        return ()

    def unsatisfiable(self, constraints: Mapping[str, tuple[Any, Mapping[str, str]]]) -> Iterable[HTTPResponse]:
        return ()

    def unknown_method(self) -> Iterable[HTTPResponse]:
        return ()
