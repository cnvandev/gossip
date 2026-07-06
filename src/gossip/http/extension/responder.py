import logging
from asyncio.tasks import gather
from http import HTTPStatus
from typing import Any, Iterable, Mapping

from gossip.http.accessor import HTTPAccessor
from gossip.http.extension.constants import Scope, Strength
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.responder import HTTPResponder
from gossip.internet.resource import ResourceCollection
from gossip.internet.uri import URI
from gossip.utils.multidict import multidict

log = logging.getLogger(__name__)


class ExtendedHTTPResponder(HTTPResponder):
    """An HTTP responder that supports HTTP message extensions.

    It properly handles extended requests and ensures mandatory/optional headers
    are respected and returns a 510 for non-conforming requests.
    """

    extensions: Mapping[URI | str, Extension]

    def __init__(
        self,
        resources: Mapping[URI, ResourceCollection],
        extensions: Iterable[Extension] | None = None,
        accessor: HTTPAccessor | None = None,
        static_headers: dict[str, str] | None = None,
    ):
        super().__init__(resources, accessor, static_headers)
        if extensions is None:
            extensions = dict()
        self.extensions = {extension.identifier: extension for extension in extensions}
        log.debug(f"Initializing with extensions: {tuple(map(str, self.extensions.keys()))}")

    async def options(self, uri: URI, constraints: Mapping[str, tuple[Any, Mapping[str, str]] | None]) -> Mapping[str, str]:
        """Returns key-value pairs describing how this responder communicates."""
        parent_options = await super().options(uri, constraints)

        # A little silly to parse and unparse it, but could be worse.
        allow_string = parent_options.get("Allow", "")
        allowed_methods = set(method.strip() for method in allow_string.split(","))
        allowed_methods |= {method.upper() for extension in self.extensions.values() for method in extension.methods.keys()}
        return {"Allow": ", ".join(allowed_methods)}

    async def successful(self, target: ResourceCollection, request: HTTPRequest, constraints: Mapping[str, tuple[Any, Mapping[str, str]]]) -> Iterable[HTTPResponse]:
        scoped_headers: dict[tuple[Scope, Strength], dict[URI | str, multidict]] = dict()
        namespaces: set[str] = set()
        non_namespaced = list()
        # We'll check all combinations of strength & scope.
        for scope in Scope:
            for strength in Strength:
                header_key = "-".join(filter(None, (scope.value, strength.value)))
                # If the request has a declaration header for that combo, parse it.
                if extension_value := request.headers.get(header_key, None):
                    scoped_headers[(scope, strength)] = dict()
                    # There could be multiple extensions, joined by a comma.
                    header_values = extension_value.split(",")
                    for value in header_values:
                        # Split into params & value, parse the namespace.
                        parts = value.strip().split(";")

                        # The first part is the URI/field name of the extension.
                        # RFC 2774: "A URI can unambiguously be distinguished from a
                        # field-name by the presence of a colon (":")."
                        # Otherwise, it's a standard header field.
                        definition = parts[0].strip('"')
                        if ":" in definition:
                            definition = URI.parse(definition)

                        # TODO: Double-check this logic, I don't know if that's the
                        # correct status to throw (or if this is the correct
                        # condition to throw it).
                        # If we don't know an extension indicated as mandatory,
                        # we throw a `501 Not Implemented`.
                        if (strength == Strength.MANDATORY) and (definition not in self.extensions):
                            log.debug(f"`{definition}` not in known extensions: {tuple(self.extensions.keys())}")
                            return (HTTPResponse(HTTPStatus.NOT_IMPLEMENTED, self.default_headers()),)

                        # Extension is known, we can parse parameters
                        stripped_args = (part.strip() for part in parts[1:])
                        pairs = (arg.split("=", maxsplit=1) for arg in stripped_args)
                        params = {pair[0]: pair[1] if len(pair) > 1 else None for pair in pairs}
                        namespace = params.get("ns", None)

                        # Now that we know the namespace, split off the headers.
                        if namespace is not None:
                            namespaces.add(namespace)
                            namespaced_headers = multidict({key.lstrip(f"{namespace}-"): value for key, value in request.headers.items()})
                            scoped_headers[(scope, strength)][definition] = namespaced_headers
                        else:
                            # Otherwise, we'll add it to the list of extensions
                            # that just use all headers.
                            non_namespaced.append((scope, strength, definition))

        # Set the extension headers for non-namespaced extensions:
        global_headers = multidict({key: value for key, value in request.headers.items() if not namespaces or not any(key.startswith(f"{namespace}-") for namespace in namespaces)})
        for scope, strength, definition in non_namespaced:
            scoped_headers[(scope, strength)][definition] = global_headers

        # For every extension in the request, process it with its headers:
        for (scope, strength), req_extensions in scoped_headers.items():
            for definition, extension_headers in req_extensions.items():
                if definition in self.extensions:
                    extension = self.extensions[definition]
                    rep_check = extension.is_representable(request.method.lstrip("M-"), extension_headers)
                    # It should return a similar format to ResourceCollection.is_acceptable(),
                    if not all(rep_check.values()):
                        failures = {header for header, value in rep_check.items() if not value}
                        raise TypeError(f"Extension {definition} found, but constraints not met: {', '.join(failures)}")

        # The extension framework prefixes the method with `M-` for requests
        # with mandatory headers, so they're not confused with regular requests.
        method_parts = request.method.split("-")
        mandatory_headers = any(strength == Strength.MANDATORY for _, strength in scoped_headers.keys())
        mandatory_method = (len(method_parts) > 1) and (method_parts[0] == "M")
        if mandatory_method and mandatory_headers:
            # We have mandatory headers in this request, we'll process it with
            # the M- prefix stripped.
            request = request.__class__(method_parts[1], request.target, request.headers, request.body)

        # Passed all checks, respond normally.
        valid_extensions = tuple(e for e in self.extensions.values() if request.method in e.methods)
        if valid_extensions:
            tasks = (ex.access(target, request, constraints, self.default_headers()) for ex in valid_extensions)
            extension_responses = await gather(*tasks)
            return (response for extension in extension_responses for response in extension)
        else:
            # Fall back to the default successful responder.
            return await super().successful(target, request, constraints)
