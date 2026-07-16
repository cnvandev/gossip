import logging
from typing import Any, Iterable, Mapping

from gossip.http.accessor import HTTPAccessor
from gossip.http.extension.framework import Extension
from gossip.http.extension.responder import ExtendedHTTPResponder
from gossip.http.message import HTTPResponse
from gossip.http.resource import ResourceCollection
from gossip.internet.uri import URI

log = logging.getLogger(__name__)


class SSDPResponder(ExtendedHTTPResponder):
    """A special type of HTTP responder that doesn't send error replies."""

    def __init__(
        self,
        resources: Mapping[URI, ResourceCollection],
        extensions: Iterable[Extension] | None = None,
        accessor: HTTPAccessor | None = None,
        static_headers: dict[str, str] | None = None,
    ):
        super().__init__(resources, extensions, accessor, static_headers)

    def unidentifiable(self, error: Exception | None = None) -> Iterable[HTTPResponse]:
        return tuple()

    def unsatisfiable(self, constraints: Mapping[str, tuple[Any, Mapping[str, str]]]) -> Iterable[HTTPResponse]:
        return tuple()

    def unknown_method(self) -> Iterable[HTTPResponse]:
        return tuple()
