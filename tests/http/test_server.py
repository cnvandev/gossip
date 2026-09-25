from http import HTTPMethod, HTTPStatus
from ipaddress import IPv4Address

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.http.responder import HTTPResponder
from gossip.http.server import HTTPServer
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio
from gossip.network.replier import Replier

from ..support.http import echo_request
from ..support.network import free_tcp_port
from ..support.resources import InMemoryResource

LOOPBACK = IPv4Address("127.0.0.1")
THING = URI.parse("/thing")


class TestHTTPServerInit:
    """Building an `HTTPServer` - wires a `Replier` to a `HTTPResponder`
    for the given resources."""

    def test_stores_the_given_resources(self):
        """`resources` is stored exactly as given."""
        resources = {THING: InMemoryResource()}
        server = HTTPServer(resources, radio_replier(Radio.loopback()))
        assert server.resources == resources

    def test_stores_a_given_replier_and_responder(self):
        """A given `replier` and `responder` are used as-is."""
        replier = radio_replier(Radio.loopback())
        responder = HTTPResponder({THING: InMemoryResource()})
        server = HTTPServer({THING: InMemoryResource()}, replier, responder)
        assert server.replier is replier
        assert server.responder is responder

    def test_defaults_to_an_http_responder_over_the_given_resources(self):
        """Omitting `responder` builds an `HTTPResponder` serving
        `resources`."""
        resource = InMemoryResource()
        server = HTTPServer({THING: resource}, radio_replier(Radio.loopback()))
        assert isinstance(server.responder, HTTPResponder)
        assert server.responder.resources[THING] is resource

    def test_default_replier_listens_on_tcp_port_80_via_the_responder(self):
        """Omitting `replier` builds one listening on TCP port 80 that
        calls back into the server's own responder (regression: it used
        to read `self.responder` before it was assigned)."""
        server = HTTPServer({})
        assert isinstance(server.replier, Replier)
        assert list(server.replier.tcp) == [80]
        assert server.replier.callback == server.responder.respond

    def test_summary_counts_domains_and_addresses(self):
        """`summary` counts resources by domain (`*` for none) and
        includes every address the replier's radio is bound to."""
        resources = {THING: InMemoryResource(), URI.parse("//example.com/other"): InMemoryResource()}
        server = HTTPServer(resources, radio_replier(Radio.loopback()))
        assert server.summary == {"*": 1, "example.com": 1, "127.0.0.1": 1}


class TestHTTPServerServerFor:
    """`HTTPServer.server_for()` wraps a single resource in the
    `{path: resource}` mapping the constructor expects."""

    def test_serves_the_resource_at_the_given_path(self):
        """The resource is served at `path`, with other keyword args
        forwarded to `__init__`."""
        resource = InMemoryResource()
        replier = radio_replier(Radio.loopback())
        server = HTTPServer.server_for(resource, "/custom", replier=replier)
        assert server.resources == {URI.parse("/custom"): resource}
        assert server.replier is replier

    def test_defaults_the_path_to_the_root(self):
        """Omitting `path` serves the resource at `/`."""
        resource = InMemoryResource()
        server = HTTPServer.server_for(resource, replier=radio_replier(Radio.loopback()))
        assert server.resources == {URI.parse("/"): resource}


class TestHTTPServerContextManager:
    """Entering an `HTTPServer` starts its replier listening; exiting
    stops it."""

    async def test_serves_requests_while_entered_and_stops_on_exit(self):
        """A real request over TCP gets the resource's representation
        while entered, and the listener is closed after exiting."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)
        resource = InMemoryResource(b"hi", {"Content-Type": "text/plain"})
        responder = HTTPResponder({THING: resource})
        replier = Replier(callback=responder.respond, tcp={port: HTTPRequest.read_from}, radio=radio)

        async with HTTPServer({THING: resource}, replier, responder) as server:
            assert server is not None
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            async with await prompter.prompt_tcp(HTTPRequest(HTTPMethod.HEAD, THING), Endpoint(LOOPBACK, port)) as session:
                reply = await session.read_reply()
                assert reply is not None
                assert reply.status == HTTPStatus.OK
                assert reply.headers["Content-Type"] == "text/plain"

        assert not replier.tcp_servers[0].is_serving()


def radio_replier(radio: Radio) -> Replier[HTTPRequest]:
    """A `Replier` bound to `radio`'s loopback, for constructing a
    server without needing the machine's real interfaces."""
    return Replier(callback=echo_request, tcp={0: HTTPRequest.read_from}, radio=radio)
