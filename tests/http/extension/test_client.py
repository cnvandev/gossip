import asyncio
from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

from netifaces import AF_INET

from gossip.http.extension.client import ExtendedHTTPClient
from gossip.http.extension.constants import Scope, Strength
from gossip.http.extension.framework import Extension
from gossip.http.field import parse_field_values
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.uri import URI
from gossip.network.binding import Binding
from gossip.network.interface import Interface
from gossip.network.radio import Radio
from gossip.network.replier import Replier

from ...support.http import echo_request
from ...support.network import free_tcp_port, free_udp_port

LOOPBACK = IPv4Address("127.0.0.1")
MULTICAST_GROUP = IPv4Address("239.255.255.250")


class TestExtendedHTTPClientExtendWithNoExtensions:
    """`ExtendedHTTPClient.extend()` with nothing to declare - just passes
    the method and headers through unchanged."""

    def test_method_is_unchanged_with_no_mandatory_extensions(self):
        """With nothing mandatory, the method is passed through as-is."""
        method, _ = ExtendedHTTPClient().extend(HTTPMethod.GET, None, None)
        assert method == HTTPMethod.GET

    def test_given_headers_are_kept_as_is(self):
        """Given headers are kept, with nothing added or removed."""
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, {"Host": "example.com"}, None)
        assert headers == {"Host": "example.com"}

    def test_a_given_connection_header_is_preserved(self):
        """A given `Connection` header is preserved as-is."""
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, {"Connection": "Upgrade, keep-alive"}, None)
        assert headers["Connection"] == "Upgrade, keep-alive"


class TestExtendedHTTPClientExtendMethodPrefix:
    """`ExtendedHTTPClient.extend()` prefixes the method with `M-` only
    when a mandatory extension is being declared."""

    def test_a_mandatory_extension_prefixes_and_upper_cases_the_method(self):
        """A mandatory extension prefixes and upper-cases the method."""
        extension = Extension("my-ext")
        method, _ = ExtendedHTTPClient().extend("get", None, {Strength.MANDATORY: {extension: {}}})
        assert method == "M-GET"

    def test_an_optional_only_extension_does_not_prefix_or_upper_case_the_method(self):
        """An optional-only extension leaves the method exactly as given."""
        extension = Extension("my-ext")
        method, _ = ExtendedHTTPClient().extend("get", None, {Strength.OPTIONAL: {extension: {}}})
        assert method == "get"


class TestExtendedHTTPClientExtendDeclarations:
    """`ExtendedHTTPClient.extend()` builds the `Man`/`Opt`/`C-Man`/`C-Opt`
    declaration header(s) naming each extension, plus its namespaced
    headers."""

    def test_a_string_identified_extension_declares_unquoted(self):
        """A string identifier declares unquoted."""
        extension = Extension("my-ext")
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {extension: {}}})
        assert headers["Man"] == "my-ext"

    def test_a_uri_identified_extension_declares_quoted(self):
        """A URI identifier declares quoted, distinguishing it from a
        field-name declaration (RFC 2774)."""
        extension = Extension(URI.parse("ssdp:discover"))
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {extension: {}}})
        assert headers["Man"] == '"ssdp:discover"'

    def test_no_namespace_is_added_with_no_namespaced_headers(self):
        """With no namespaced headers, no `ns=` is added."""
        extension = Extension("my-ext")
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {extension: {}}})
        assert "ns=" not in headers["Man"]

    def test_namespaced_headers_are_declared_and_prefixed(self):
        """Namespaced headers get a namespace and matching `<ns>-` prefix."""
        extension = Extension("my-ext")
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {extension: {"Foo": "bar"}}})
        ((_, namespaced_params),) = tuple(parse_field_values(headers["Man"]))
        namespace = namespaced_params.get("ns", "")
        assert len(namespace) == 2 and namespace.isdigit()
        assert headers[f"{namespace}-Foo"] == "bar"

    def test_optional_strength_uses_the_opt_declaration_header(self):
        """Optional strength uses `Opt` rather than `Man`."""
        extension = Extension("my-ext")
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.OPTIONAL: {extension: {}}})
        assert headers["Opt"] == "my-ext"
        assert "Man" not in headers

    def test_hop_by_hop_scope_uses_the_c_prefixed_declaration_header(self):
        """Hop-by-hop scope uses `C-Man` rather than plain `Man`."""
        extension = Extension("my-ext", scope=Scope.HOP_BY_HOP)
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {extension: {}}})
        assert headers["C-Man"] == "my-ext"

    def test_multiple_extensions_of_the_same_strength_and_scope_are_comma_joined(self):
        """Multiple extensions of the same strength/scope share one
        comma-joined declaration header."""
        first = Extension("ext-one")
        second = Extension("ext-two")
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {first: {}, second: {}}})
        assert headers["Man"] == "ext-one,ext-two"


class TestExtendedHTTPClientExtendHopByHopConnection:
    """Hop-by-hop declarations and namespaced headers get listed in the
    `Connection` header, per RFC 2774."""

    def test_hop_by_hop_namespaced_headers_are_listed_in_connection(self):
        """A hop-by-hop extension's namespaced headers are listed in `Connection`."""
        extension = Extension("my-ext", scope=Scope.HOP_BY_HOP)
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {extension: {"Foo": "bar"}}})
        ((_, namespaced_params),) = tuple(parse_field_values(headers["C-Man"]))
        namespace = namespaced_params.get("ns", "")
        connection_entries = {entry.strip() for entry in headers["Connection"].split(",")}
        assert f"{namespace}-Foo" in connection_entries

    def test_end_to_end_scope_is_not_listed_in_connection(self):
        """An end-to-end extension's headers aren't listed in `Connection`."""
        extension = Extension("my-ext", scope=Scope.END_TO_END)
        _, headers = ExtendedHTTPClient().extend(HTTPMethod.GET, None, {Strength.MANDATORY: {extension: {"Foo": "bar"}}})
        assert "Connection" not in headers


class TestExtendedHTTPClientRequestTcp:
    """`ExtendedHTTPClient.request_tcp()` extends the request, then sends
    it over a real TCP connection the same way `HTTPClient.request()`
    does."""

    async def test_sends_the_extended_method_and_declaration(self):
        """A mandatory extension's `M-`-prefixed method and declaration
        header actually reach the server."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)
        extension = Extension("my-ext")

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            client = ExtendedHTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")

            async with await client.request_tcp("get", uri, extended_headers={Strength.MANDATORY: {extension: {}}}) as session:
                response = await session.read_reply()

                assert response is not None
                assert response.status == HTTPStatus.OK
                assert response.headers["Test-Request-Method"] == "M-GET"
            assert response.headers["Test-Request-Man"] == "my-ext"


class TestExtendedHTTPClientRequestUdp:
    """`ExtendedHTTPClient.request_udp()` extends the request, then sends
    it over UDP and returns the deserialized reply."""

    async def test_sends_the_extended_method_and_declaration(self):
        """A mandatory extension's `M-`-prefixed method and declaration
        header actually reach the server."""
        radio = Radio.loopback()

        async with Replier(callback=echo_request, udp={0: HTTPRequest.read_from}, radio=radio) as replier:
            _, port = replier.udp_transports[0].get_extra_info("sockname")
            extension = Extension("my-ext")

            client = ExtendedHTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")
            response = await client.request_udp("get", uri, extended_headers={Strength.MANDATORY: {extension: {}}})

            assert response is not None
            assert response.status == HTTPStatus.OK
            assert response.headers["Test-Request-Method"] == "M-GET"
            assert response.headers["Test-Request-Man"] == "my-ext"


class TestExtendedHTTPClientBroadcast:
    """`ExtendedHTTPClient.broadcast()` extends the request, then
    broadcasts it and gathers raw replies the same way
    `Prompter.broadcast()` does."""

    async def test_sends_the_extended_method_and_declaration(self):
        """A mandatory extension's `M-`-prefixed method and declaration
        header actually reach whoever's listening."""
        responder_radio = Radio.loopback()
        port = await free_udp_port(responder_radio)

        # `broadcast=None` sends the datagram to the binding's own
        # address (this test's `Replier`) instead of `MULTICAST_GROUP` -
        # which still has to be a real multicast address, since joining
        # it as a group happens regardless of where the datagram is sent.
        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),))
        extension = Extension("my-ext")

        async with Replier(callback=echo_request, udp={port: HTTPRequest.read_from}, radio=responder_radio):
            client = ExtendedHTTPClient(radio=radio)
            uri = URI.http(f"//{MULTICAST_GROUP}:{port}/")
            future = await client.broadcast("get", uri, extended_headers={Strength.MANDATORY: {extension: {}}})
            [result] = await asyncio.wait_for(future, timeout=2)

            assert result is not None
            reply = await HTTPResponse.read_from(result)
            assert reply is not None
            assert reply.status == HTTPStatus.OK
            assert reply.headers["Test-Request-Method"] == "M-GET"
            assert reply.headers["Test-Request-Man"] == "my-ext"


class TestExtendedHTTPClientBroadcastRequest:
    """`ExtendedHTTPClient.broadcast_request()` extends the request, then
    streams back deserialized replies the same way
    `Prompter.broadcast_prompt()` does."""

    async def test_streams_the_extended_methods_reply(self):
        """A mandatory extension's `M-`-prefixed method and declaration
        header actually reach whoever's listening."""
        responder_radio = Radio.loopback()
        port = await free_udp_port(responder_radio)

        radio = Radio((Interface("lo0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),))
        extension = Extension("my-ext")

        async with Replier(callback=echo_request, udp={port: HTTPRequest.read_from}, radio=responder_radio):
            client = ExtendedHTTPClient(radio=radio)
            uri = URI.http(f"//{MULTICAST_GROUP}:{port}/")
            replies = await client.broadcast_request("get", uri, extended_headers={Strength.MANDATORY: {extension: {}}})

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.status == HTTPStatus.OK
                assert reply.headers["Test-Request-Method"] == "M-GET"
                assert reply.headers["Test-Request-Man"] == "my-ext"
