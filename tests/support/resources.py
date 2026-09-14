"""Shared `ResourceCollection` test doubles.

Not a test module - imported by tests that need a target resource to route
a request to, without a real resource behind it.
"""

from collections.abc import Mapping
from typing import Any

from gossip.http.resource import ResourceCollection
from gossip.internet.predicate import RequestPredicate
from gossip.internet.uri import URI
from gossip.network.serializer import BufferedReader


class InMemoryResource(ResourceCollection):
    """A minimal, genuinely working `ResourceCollection` - actually
    stores and mutates a body, rather than recording which method was
    called. Lets a test assert on the real representation (or lack of
    one) a request produces, instead of on which method ran."""

    def __init__(self, body: bytes = b"", metadata: Mapping[str, str] | None = None, predicates: Mapping[str, RequestPredicate] | None = None):
        super().__init__(predicates)
        self.body = body
        self.metadata = dict(metadata or {})

    async def options(self, uri: URI, constraints: Mapping[str, Any]) -> Mapping[str, str]:
        return {"Allow": "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"}

    async def represent(self, exact_uri: URI, constraints: Mapping[str, Any]):
        return BufferedReader.for_bytes(self.body), dict(self.metadata)

    async def write(self, exact_uri: URI, constraints: Mapping[str, Any], request_body):
        self.body = await request_body.read() if request_body is not None else b""
        return BufferedReader.for_bytes(self.body), dict(self.metadata)

    async def patch(self, exact_uri: URI, constraints: Mapping[str, Any], patch):
        self.body += await patch.read() if patch is not None else b""
        return BufferedReader.for_bytes(self.body), dict(self.metadata)

    async def delete(self, exact_uri: URI, constraints: Mapping[str, Any]):
        deleted, self.body = self.body, b""
        return BufferedReader.for_bytes(deleted), dict(self.metadata)
