from http import HTTPStatus
from ipaddress import IPv4Address, IPv6Address

from gossip.dns.client import DNSClient
from gossip.dns.message import RecordType
from gossip.http.client import HTTPClient
from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.session import HTTPSession
from gossip.internet.product import ProductStack
from gossip.internet.uri import URI
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio
from gossip.network.replier import Replier

from ..support.asyncio import wait_closing
from ..support.http import echo_request
from ..support.network import free_tcp_port

LOOPBACK = IPv4Address("127.0.0.1")
ROOT = URI.parse("/")


class FakeDNSClient(DNSClient):
    """Resolves every hostname to a fixed IP address, without touching a
    real DNS server."""

    def __init__(self, address: IPv4Address | IPv6Address):
        self.address = address

    async def resolve_ip(self, domain: str, qtype: RecordType = RecordType.A, roots=None, port: int = 53) -> IPv4Address | IPv6Address:
        return self.address


class TestHTTPClientInit:
    """Building an `HTTPClient`."""

    def test_defaults_to_the_gossip_agent(self):
        """Omitting `agent` defaults to the `gossip` product stack."""
        client = HTTPClient(radio=Radio.loopback())
        assert client.agent == ProductStack.gossip()

    def test_stores_the_given_agent(self):
        """A given `agent` is stored as-is."""
        agent = ProductStack.gossip()
        client = HTTPClient(agent=agent, radio=Radio.loopback())
        assert client.agent is agent

    def test_defaults_to_a_dns_client(self):
        """Omitting `dns` builds a real `DNSClient`."""
        client = HTTPClient(radio=Radio.loopback())
        assert isinstance(client.dns, DNSClient)

    def test_stores_the_given_dns_client(self):
        """A given `dns` is stored as-is."""
        dns = FakeDNSClient(LOOPBACK)
        client = HTTPClient(dns=dns, radio=Radio.loopback())
        assert client.dns is dns

    def test_defaults_to_a_prompter(self):
        """Omitting `prompter` builds a real `Prompter`."""
        client = HTTPClient(radio=Radio.loopback())
        assert isinstance(client.prompter, Prompter)

    def test_stores_the_given_prompter(self):
        """A given `prompter` is stored as-is."""
        prompter = Prompter(HTTPResponse.read_from, radio=Radio.loopback())
        client = HTTPClient(prompter=prompter)
        assert client.prompter is prompter


class TestHTTPClientDefaultHeaders:
    """`HTTPClient.default_headers()` - just a `User-Agent` from `agent`."""

    def test_returns_the_agent_as_the_user_agent(self):
        """`User-Agent` is the client's own `agent`, stringified."""
        agent = ProductStack.gossip()
        client = HTTPClient(agent=agent, radio=Radio.loopback())
        assert client.default_headers() == {"User-Agent": str(agent)}


class TestHTTPClientPrepare:
    """`HTTPClient.prepare()` builds the request and destination for a
    method/URI/headers triple."""

    async def test_builds_the_request_with_the_given_method_and_headers(self):
        """The request carries the given method and any given headers."""
        client = HTTPClient(radio=Radio.loopback())
        request, _ = await client.prepare("GET", URI.http("//example.com/foo"), {"X-Test": "yes"})
        assert request.method == "GET"
        assert request.headers["X-Test"] == "yes"

    async def test_strips_the_scheme_and_netloc_from_the_request_target(self):
        """The request's own target is just the path, not the full URI."""
        client = HTTPClient(radio=Radio.loopback())
        request, _ = await client.prepare("GET", URI.http("//example.com/foo"))
        assert str(request.target) == "/foo"

    async def test_adds_a_host_header_from_the_uris_netloc(self):
        """`Host` is set from the URI's own netloc."""
        client = HTTPClient(radio=Radio.loopback())
        request, _ = await client.prepare("GET", URI.http("//example.com:8080/foo"))
        assert request.headers["Host"] == "example.com:8080"

    async def test_adds_a_user_agent_header_from_the_client(self):
        """`User-Agent` is set from the client's own `agent`."""
        agent = ProductStack.gossip()
        client = HTTPClient(agent=agent, radio=Radio.loopback())
        request, _ = await client.prepare("GET", URI.http("//example.com/foo"))
        assert request.headers["User-Agent"] == str(agent)

    async def test_resolves_a_literal_ip_host_without_dns(self):
        """A literal IP host is used directly, with no DNS lookup."""
        client = HTTPClient(radio=Radio.loopback())
        _, destination = await client.prepare("GET", URI.http("//127.0.0.1/foo"))
        assert destination.address == LOOPBACK

    async def test_resolves_a_hostname_via_dns(self):
        """A non-IP host is resolved via the client's `dns`."""
        client = HTTPClient(dns=FakeDNSClient(LOOPBACK), radio=Radio.loopback())
        _, destination = await client.prepare("GET", URI.http("//example.com/foo"))
        assert destination.address == LOOPBACK

    async def test_defaults_to_loopback_with_no_host_at_all(self):
        """A URI with no host at all defaults to loopback."""
        client = HTTPClient(radio=Radio.loopback())
        _, destination = await client.prepare("GET", URI.http("/foo"))
        assert destination.address == LOOPBACK

    async def test_defaults_the_port_to_80(self):
        """A URI with no explicit port defaults to port 80."""
        client = HTTPClient(radio=Radio.loopback())
        _, destination = await client.prepare("GET", URI.http("//127.0.0.1/foo"))
        assert destination.port == 80

    async def test_uses_the_given_port(self):
        """An explicit port in the URI is used as-is."""
        client = HTTPClient(radio=Radio.loopback())
        _, destination = await client.prepare("GET", URI.http("//127.0.0.1:8080/foo"))
        assert destination.port == 8080


class TestHTTPClientVerbs:
    """`HTTPClient.get()`/`post()`/`put()`/`patch()`/`delete()`/`head()`
    each send a real HTTP request over TCP and return the deserialized
    response."""

    async def test_each_verb_sends_its_own_method_and_returns_the_response(self):
        """Each convenience method sends its own HTTP method, and gets
        back a real, deserialized response."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")

            for method_name in ["get", "post", "put", "patch", "delete", "head"]:
                response = await getattr(client, method_name)(uri)
                assert response is not None
                assert response.status == HTTPStatus.OK
                assert response.headers["Test-Request-Method"] == method_name.upper()
                assert response.headers["Test-Request-Target"] == uri.path

    async def test_forces_connection_close_regardless_of_headers(self):
        """Each verb method sends `Connection: close`, even if the
        caller passed their own `Connection` header."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")
            response = await client.get(uri, {"Connection": "keep-alive"})

            assert response is not None
            assert response.headers["Test-Request-Connection"] == "close"


class TestHTTPClientRequest:
    """`HTTPClient.request()` opens an `HTTPSession`, sending `method`
    as the session's own first request."""

    async def test_returns_a_session_with_the_first_reply_readable(self):
        """The reply to `request()`'s own first message is readable
        straight off the returned session."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")

            async with await client.request("GET", uri) as session:
                assert isinstance(session, HTTPSession)
                reply = await session.read_reply()

                assert reply is not None
                assert reply.status == HTTPStatus.OK
                assert reply.headers["Test-Request-Method"] == "GET"

    async def test_is_async_iterable_over_its_replies(self):
        """`async for` on the session delegates to the underlying
        `PromptSession`, same as `read_reply()`."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")

            async with await client.request("GET", uri) as session:
                async for reply in session:
                    assert reply.status == HTTPStatus.OK
                    break

    async def test_defaults_to_connection_keep_alive(self):
        """`Connection: keep-alive` is sent unless `headers` overrides
        it."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")

            async with await client.request("GET", uri) as session:
                reply = await session.read_reply()
                assert reply is not None
                assert reply.headers["Test-Request-Connection"] == "keep-alive"

    async def test_reuses_the_connection_for_a_second_request(self):
        """A second request sent via the session's own verb methods goes
        down the same TCP connection as the first - the server here only
        ever accepts one connection, and reads two requests off it."""

        async def on_connection(reader, writer):
            for _ in range(2):
                request = await HTTPRequest.read_from(reader)
                assert request is not None
                await HTTPResponse(HTTPStatus.OK, {"Test-Echo-Target": str(request.target)}).write_to(writer)
            writer.close()
            await writer.wait_closed()

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/one")

            async with await client.request("GET", uri) as session:
                first_reply = await session.read_reply()
                assert first_reply is not None
                assert first_reply.headers["Test-Echo-Target"] == "/one"

                second_reply = await session.get(URI.parse("/two"))
                assert second_reply is not None
                assert second_reply.headers["Test-Echo-Target"] == "/two"

    async def test_session_verb_methods_send_their_own_method(self):
        """Each of the session's verb methods sends its own HTTP method,
        down the same connection as the request that opened it."""

        async def on_connection(reader, writer):
            for _ in range(6):
                request = await HTTPRequest.read_from(reader)
                assert request is not None
                await HTTPResponse(HTTPStatus.OK, {"Test-Echo-Method": request.method}).write_to(writer)
            writer.close()
            await writer.wait_closed()

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")

            async with await client.request("GET", uri) as session:
                first_reply = await session.read_reply()
                assert first_reply is not None
                assert first_reply.headers["Test-Echo-Method"] == "GET"

                for method_name in ["post", "put", "patch", "delete", "head"]:
                    reply = await getattr(session, method_name)(ROOT)
                    assert reply is not None
                    assert reply.headers["Test-Echo-Method"] == method_name.upper()

    async def test_get_returns_none_for_an_unparseable_reply(self):
        """A verb method returns `None` if its reply can't be parsed,
        same as `request()`'s own first message does."""

        async def on_connection(reader, writer):
            first_request = await HTTPRequest.read_from(reader)
            assert first_request is not None
            await HTTPResponse(HTTPStatus.OK).write_to(writer)

            second_request = await HTTPRequest.read_from(reader)
            assert second_request is not None
            writer.write(b"not a valid HTTP message\r\n\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            client = HTTPClient(radio=radio)
            uri = URI.http(f"//127.0.0.1:{port}/")

            async with await client.request("GET", uri) as session:
                first_reply = await session.read_reply()
                assert first_reply is not None

                second_reply = await session.get(ROOT)
                assert second_reply is None
