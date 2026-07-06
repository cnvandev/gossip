import logging
from typing import Any, Awaitable, Callable, Iterable, Mapping

from gossip.http.accessor import HTTPAccessor
from gossip.http.extension.constants import Scope, Strength
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.utils.multidict import multidict

log = logging.getLogger(__name__)


class Extension(HTTPAccessor):
    """An extension to support additional features for accessing HTTP resources.

    It's an HTTPAccessor so any identified resources can be accessed via its
    methods. It's designed so that subclasses will be able to subclass it and
    treat the requests differently (although the framework was never adopted
    outside of SSDP.)
    """

    identifier: URI | str
    headers: Mapping[str, Mapping[Strength, Mapping[str, Callable[[str], Any]]]]
    scope: Scope
    namespace: str | None

    def __init__(
        self,
        identifier: URI | str,
        headers: Mapping[str, Mapping[Strength, Mapping[str, Callable[[str], Any]]]],
        methods: Mapping[str, Callable[[ResourceCollection, URI, Mapping[str, tuple[Any, Mapping[str, str]] | None], Mapping[str, str]], Awaitable[Iterable[HTTPResponse]]]] | None = None,
        scope: Scope = Scope.END_TO_END,
        namespace: str | None = None,
    ):
        super().__init__(methods)
        self.identifier = identifier
        self.headers = headers
        self.scope = scope
        self.namespace = namespace

    async def access(self, resource: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None], headers: Mapping[str, str]) -> Iterable[HTTPResponse]:
        # Successful extension usage puts in this header, to indicate an
        # extension was used successfully.
        extension_headers = {"Ext": ""}
        return await super().access(resource, request, constraints, headers | extension_headers)

    def declaration_key(self, method: str) -> str:
        """Get the general header key for this extension declaration."""
        return "-".join(filter(None, map(str, (self.scope, self.methods[method]))))

    def extended_key(self, key: str) -> str:
        """Get the namespace-scoped key for an header under an extension."""
        return "-".join(filter(None, (self.namespace, key)))

    def declaration(self):
        """Get the string representation of the extension declaration."""
        parts = (f'"{self.identifier}"',)
        if self.namespace is not None:
            parts += (f"ns={self.namespace}",)
        return "; ".join(parts)

    def is_representable(self, method: str, headers: multidict) -> dict[str, Any]:
        """Returns whether a message's target is representable, given a request
        with the headers.
        """
        return {header: parser(headers[header]) for strength, extension_headers in self.headers[method].items() for header, parser in extension_headers.items() if strength == Strength.MANDATORY}
