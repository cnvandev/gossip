from asyncio import run as run_async
from http import HTTPMethod
from ipaddress import IPv4Address

from gossip.http.extension.constants import Scope
from gossip.http.extension.framework import Extension
from gossip.http.message import HTTPRequest
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint

from ...support.resources import InMemoryResource

TARGET = URI.parse("/foo")
REMOTE = Endpoint(IPv4Address("10.0.0.1"), 54321)
LOCAL = Endpoint(IPv4Address("10.0.0.2"), 80)


class TestExtensionConstruction:
    """Building an `Extension` - it's also an `HTTPAccessor`, so it gets
    the same default method table on top of its own `identifier`/`scope`."""

    def test_scope_defaults_to_end_to_end(self):
        """Omitting `scope` defaults to end-to-end, not hop-by-hop."""
        assert Extension("my-ext").scope == Scope.END_TO_END

    def test_still_has_the_standard_accessor_methods(self):
        """The standard six accessor methods are still wired up."""
        extension = Extension("my-ext")
        assert extension.methods[HTTPMethod.GET] == extension.get


class TestExtensionHeaders:
    """`Extension.headers()` pulls this extension's own namespaced headers
    from a request, per RFC 2774."""

    def test_no_declaration_header_at_all_yields_nothing(self):
        """With no declaration header at all, nothing is returned."""
        extension = Extension("my-ext")
        headers = {
            "42-Foo": "bar",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {}

    def test_a_declaration_for_a_different_extension_yields_nothing(self):
        """A declaration naming another extension yields nothing."""
        extension = Extension("my-ext")
        headers = {
            "Man": "other-ext; ns=42",
            "42-Foo": "bar",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {}

    def test_a_declaration_with_no_namespace_yields_nothing(self):
        """Without an `ns=` param, nothing is returned."""
        extension = Extension("my-ext")
        headers = {
            "Man": "my-ext",
            "42-Foo": "bar",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {}

    def test_mandatory_declaration_recovers_the_namespaced_headers(self):
        """A `Man` declaration with a namespace recovers just that
        namespace's headers."""
        extension = Extension("my-ext")
        headers = {
            "Man": "my-ext; ns=42",
            "42-Foo": "bar",
            "Other": "unrelated",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {"Foo": "bar"}

    def test_optional_declaration_is_recognized_too(self):
        """An `Opt` declaration works the same as a `Man` one."""
        extension = Extension("my-ext")
        headers = {
            "Opt": "my-ext; ns=42",
            "42-Foo": "bar",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {"Foo": "bar"}

    def test_hop_by_hop_scope_uses_the_c_prefixed_declaration_header(self):
        """A hop-by-hop extension is declared via `C-Man`."""
        extension = Extension("my-ext", scope=Scope.HOP_BY_HOP)
        headers = {
            "C-Man": "my-ext; ns=42",
            "42-Foo": "bar",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {"Foo": "bar"}

    def test_end_to_end_scope_ignores_a_hop_by_hop_declaration(self):
        """An end-to-end extension ignores a `C-Man` declaration of itself."""
        extension = Extension("my-ext")
        headers = {
            "C-Man": "my-ext; ns=42",
            "42-Foo": "bar",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {}

    def test_a_uri_identifier_is_matched_against_the_quoted_declaration(self):
        """A URI identifier is matched via the quoted, colon-containing
        declaration form."""
        extension = Extension(URI.parse("ssdp:discover"))
        headers = {
            "Man": '"ssdp:discover"; ns=42',
            "42-Foo": "bar",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {"Foo": "bar"}

    def test_only_the_matching_entry_in_a_multi_extension_declaration_counts(self):
        """Only the entry naming this extension supplies a namespace."""
        extension = Extension("my-ext")
        headers = {
            "Man": "other-ext; ns=99, my-ext; ns=42",
            "42-Foo": "bar",
            "99-Foo": "other",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {"Foo": "bar"}

    def test_only_headers_with_the_exact_namespace_dash_prefix_are_returned(self):
        """A header starting with the same digits but no dash is excluded."""
        extension = Extension("my-ext")
        headers = {
            "Man": "my-ext; ns=42",
            "42-Foo": "bar",
            "420-Bar": "not-namespaced",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {"Foo": "bar"}

    def test_unrelated_headers_are_not_included(self):
        """A header outside the namespace never leaks into the result."""
        extension = Extension("my-ext")
        headers = {
            "Man": "my-ext; ns=42",
            "42-Foo": "bar",
            "Host": "example.com",
        }
        request = HTTPRequest(HTTPMethod.GET, TARGET, headers)
        assert extension.headers(request) == {"Foo": "bar"}


class TestExtensionAccess:
    """`Extension.access()` - marks a successful response with the empty
    `Ext` header, then delegates to the normal `HTTPAccessor` dispatch."""

    def test_adds_the_ext_header_to_the_response(self):
        """A successful response always carries the empty `Ext` header."""
        resource = InMemoryResource(b"hi")
        extension = Extension("my-ext")
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = run_async(extension.access(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.headers["Ext"] == ""

    def test_keeps_the_other_static_headers_given(self):
        """Adding `Ext` doesn't crowd out other static headers."""
        resource = InMemoryResource()
        extension = Extension("my-ext")
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = run_async(extension.access(resource, request, {}, {"Server": "gossip"}, REMOTE, LOCAL))
        assert response.headers["Server"] == "gossip"
        assert response.headers["Ext"] == ""

    def test_still_dispatches_by_method_like_a_plain_accessor(self):
        """A `GET` still reaches the resource's real representation."""
        resource = InMemoryResource(b"hi")
        extension = Extension("my-ext")
        request = HTTPRequest(HTTPMethod.GET, TARGET)
        (response,) = run_async(extension.access(resource, request, {}, {}, REMOTE, LOCAL))
        assert response.body is not None
        assert run_async(response.body.read()) == b"hi"
