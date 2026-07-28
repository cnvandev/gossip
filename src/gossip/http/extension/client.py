import random
from collections import defaultdict
from typing import Mapping

from aiostream import Stream

from gossip.http.client import HTTPClient
from gossip.http.extension.constants import Strength, Scope
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPResponse
from gossip.internet.uri import URI


class ExtendedHTTPClient(HTTPClient):
    """An HTTP client that sends requests with extensions."""

    def extend(self, method: str, headers: Mapping[str, str] | None = None, extended_headers: Mapping[Strength, Mapping[Extension, Mapping[str, str]]] | None = None) -> tuple[str, Mapping[str, str]]:
        if headers is None:
            headers = dict()
        else:
            # Make it mutable
            headers = dict(headers)

        if extended_headers is None:
            extended_headers = dict()

        # If there are any hop-by-hop headers, we'll put them in the Connection header.
        connection = headers.pop("Connection", "")
        connection_headers = list(map(str.strip, connection.split(",")))

        # To mark the request as mandatory, the method gets prefixed with `M-`.
        if Strength.MANDATORY in extended_headers:
            method = f"M-{method.upper()}"

        for strength, extension_headers in extended_headers.items():
            # First, add our namespaced headers to the request.
            grouped: defaultdict[Scope, list[list[str]]] = defaultdict(list)
            for extension, namespaced_headers in extension_headers.items():
                # If the identifier is a URL, we want it wrapped in quotes
                identifier = extension.identifier if isinstance(extension.identifier, str) else f"\"{extension.identifier}\""

                # The declaration is saved for later in case there are multiple
                # extensions with the same strength/scope.
                declaration = [identifier]
                if namespaced_headers:
                    # Namespace is any two-digit integer
                    namespace = f"{random.randint(10, 99):02d}"
                    declaration.append(f"ns={namespace}")

                    # Prefix the extension headers with the namespace.
                    prefixed_headers = {f"{namespace}-{key}": value for key, value in namespaced_headers.items()}
                    headers |= prefixed_headers

                    # All hop-by-hop header keys get added to the `Connection` header.
                    if extension.scope == Scope.HOP_BY_HOP:
                        connection_headers.extend(prefixed_headers.keys())

                # Saving this for the declaration later.
                grouped[extension.scope].append(declaration)

            # Then, add the extension declaration headers with the namespaces.
            for scope, extensions in grouped.items():
                declaration_key = "-".join(filter(None, (scope, strength)))
                headers[declaration_key] = ",".join(";".join(stuff) for stuff in extensions)

                # Add the hop-by-hop declaration key to the `Connection` header.
                if scope == Scope.HOP_BY_HOP:
                    connection_headers.extend(declaration_key)

        if connection_headers:
            headers["Connection"] = ", ".join(connection_headers)

        return method, headers

    async def request_tcp(self,
        method: str, uri: URI, headers: Mapping[str, str] | None = None,
        extended_headers: Mapping[Strength, Mapping[Extension, Mapping[str, str]]] | None = None,
    ) -> HTTPResponse | None:
        """Make an extended HTTP request, with the extended headers."""
        method, headers = self.extend(method, headers, extended_headers)
        return await super().request(method, uri, headers)

    async def request_udp(self,
        method: str, uri: URI, headers: Mapping[str, str] | None = None,
        extended_headers: Mapping[Strength, Mapping[Extension, Mapping[str, str]]] | None = None,
    ) -> HTTPResponse | None:
        """Make an extended HTTP request, with the extended headers."""
        method, headers = self.extend(method, headers, extended_headers)
        request, destination = self.prepare(method, uri, headers)
        return await self.prompter.prompt_udp(request, destination)

    async def broadcast(self,
        method: str, uri: URI, headers: Mapping[str, str] | None = None,
        extended_headers: Mapping[Strength, Mapping[Extension, Mapping[str, str]]] | None = None,
    ) -> None:
        """Make an extended HTTP request, with the extended headers."""
        method, headers = self.extend(method, headers, extended_headers)
        request, destination = self.prepare(method, uri, headers)
        return await self.prompter.broadcast(request, destination)

    async def broadcast_request(self,
        method: str, uri: URI, headers: Mapping[str, str] | None = None,
        extended_headers: Mapping[Strength, Mapping[Extension, Mapping[str, str]]] | None = None,
        tcp_port: int | None = None, max_wait: int = 5
    ) -> Stream[HTTPResponse]:
        """Make an extended HTTP request, with the extended headers."""
        method, headers = self.extend(method, headers, extended_headers)
        request, destination = self.prepare(method, uri, headers)
        return await self.prompter.broadcast_prompt(request, destination, tcp_port=tcp_port, max_wait=max_wait)
