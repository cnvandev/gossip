import asyncio
import contextlib
from http import HTTPStatus
from ipaddress import IPv4Address

import pytest
from netifaces import AF_INET

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.uri import URI
from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface
from gossip.network.prompter import Prompter, queue_iterator
from gossip.network.radio import Radio
from gossip.network.replier import Replier

from ..support.asyncio import StaticReplyProtocol, wait_closing
from ..support.http import echo_request
from ..support.network import free_tcp_port
from ..support.streams import RecordingWriter

LOOPBACK = IPv4Address("127.0.0.1")
MULTICAST_GROUP = IPv4Address("239.255.255.250")
ROOT = URI.parse("/")


class TestPrompterInit:
    """Building a `Prompter`."""

    def test_stores_the_deserializer(self):
        """`deserializer` is stored as given."""
        prompter = Prompter(HTTPResponse.read_from, radio=Radio.loopback())
        assert prompter.deserializer == HTTPResponse.read_from

    def test_stores_the_given_radio(self):
        """A given `radio` is stored as-is."""
        radio = Radio.loopback()
        prompter = Prompter(HTTPResponse.read_from, radio=radio)
        assert prompter.radio is radio

    def test_defaults_to_a_real_netifaces_radio(self):
        """Omitting `radio` builds a real one from the machine's own
        interfaces, rather than leaving it unset."""
        prompter = Prompter(HTTPResponse.read_from)
        assert isinstance(prompter.radio, Radio)


class TestPrompterPromptTcp:
    """`Prompter.prompt_tcp()` sends a prompt over a real TCP connection
    and returns the deserialized reply."""

    async def test_returns_the_deserialized_reply(self):
        """The reply written back is read and deserialized, carrying
        back what the server actually received."""
        radio = Radio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))

            assert reply is not None
            assert reply.status == HTTPStatus.OK
            assert reply.headers["Test-Request-Method"] == "GET"

    async def test_leaves_the_connection_open_for_a_non_terminal_reply(self):
        """A reply that isn't terminal (HTTP/1.1, no `Connection` header)
        leaves the connection open once `prompt_tcp()` returns.

        Checked by recording whether `prompt_tcp()` itself ever called
        `close()`, rather than by watching the peer for an EOF - an
        abandoned-but-not-explicitly-closed `StreamWriter` still gets
        closed by its own `__del__` once nothing references it, and
        *when* that happens is up to the garbage collector, not
        `prompt_tcp()`. That makes EOF an unreliable signal here (see
        `RecordingWriter`)."""

        class RecordingRadio(Radio):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.writer: RecordingWriter | None = None

            async def tcp_send(self, remote):
                reader, writer = await super().tcp_send(remote)
                self.writer = RecordingWriter(writer)
                return reader, self.writer

        radio = RecordingRadio.loopback()
        port = await free_tcp_port(radio)

        async with Replier(callback=echo_request, tcp={port: HTTPRequest.read_from}, radio=radio):
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))

            assert reply is not None
            assert reply.is_terminal() is False
            assert radio.writer is not None
            assert radio.writer.closed is False

            # Our own code chose not to close it - we still have to, so
            # the connection doesn't leak past this test.
            radio.writer.close()
            await radio.writer.wait_closed()

    async def test_closes_the_connection_for_a_terminal_reply(self):
        """A reply with `Connection: close` closes the connection once
        `prompt_tcp()` returns - observed as EOF from the server side."""
        loop = asyncio.get_running_loop()
        connection = loop.create_future()

        async def on_connection(reader, writer):
            await HTTPRequest.read_from(reader)
            await HTTPResponse(HTTPStatus.OK, {"Connection": "close"}).write_to(writer)
            connection.set_result((reader, writer))

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))
            assert reply is not None

            server_reader, server_writer = await connection
            data = await asyncio.wait_for(server_reader.read(), timeout=0.5)
            assert data == b""

            # The client already closed its end; close ours too, so
            # `wait_closing(server)` below doesn't hang - `asyncio.Server`
            # tracks its accepted connections and won't consider itself
            # closed until they are too.
            server_writer.close()
            await server_writer.wait_closed()

    async def test_returns_none_for_an_unparseable_reply(self):
        """A reply the deserializer can't parse comes back as `None`."""

        async def on_connection(reader, writer):
            await HTTPRequest.read_from(reader)
            writer.write(b"not a valid HTTP message\r\n\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))

            assert reply is None


class TestPrompterPromptUdp:
    """`Prompter.prompt_udp()` sends a prompt over UDP and awaits the
    reply - either on the same UDP socket, or over TCP if a `tcp_port`
    is given."""

    async def test_returns_the_deserialized_reply_over_the_same_udp_socket(self):
        """Without a `tcp_port`, the reply arrives on the same UDP
        transport the prompt was sent from."""
        loop = asyncio.get_running_loop()

        fixed_reply = bytes(HTTPResponse(HTTPStatus.OK))
        responder_transport, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(fixed_reply), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(responder_transport):
            _, responder_port = responder_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=Radio.loopback())
            reply = await prompter.prompt_udp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, responder_port))

            assert reply is not None
            assert reply.status == HTTPStatus.OK

    async def test_returns_none_for_an_unparseable_udp_reply(self):
        """A reply the deserializer can't parse comes back as `None`,
        rather than raising."""
        loop = asyncio.get_running_loop()

        responder_transport, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(b"not a valid HTTP message\r\n\r\n"), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(responder_transport):
            _, responder_port = responder_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=Radio.loopback())
            reply = await prompter.prompt_udp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, responder_port))

            assert reply is None

    async def test_raises_on_timeout_with_no_reply(self):
        """A real listener that never replies leaves the prompt
        unanswered, so it times out."""
        loop = asyncio.get_running_loop()

        silent_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(silent_transport):
            _, silent_port = silent_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=Radio.loopback())
            with pytest.raises(TimeoutError):
                await prompter.prompt_udp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, silent_port))

    async def test_returns_none_when_the_connection_closes_with_nothing_received(self):
        """The connection closing with nothing ever received comes back
        as `None`, the same as an unparseable reply does.

        Nothing in `prompt_udp()`'s own code path closes its UDP
        transport before a reply or a timeout, so this forces it via a
        `Radio` that closes its own `udp_send()` transport immediately
        - simulating a real connection-closed condition rather than
        one `prompt_udp()` could ever trigger itself."""

        class SelfClosingRadio(Radio):
            async def udp_send(self, endpoint):
                transport, protocol = await super().udp_send(endpoint)
                transport.close()
                return transport, protocol

        radio = SelfClosingRadio((Interface("lo0", {AF_INET: (Binding(LOOPBACK),)}),))
        prompter = Prompter(HTTPResponse.read_from, radio=radio)
        reply = await prompter.prompt_udp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, 1))

        assert reply is None

    async def test_returns_the_deserialized_reply_over_tcp_when_a_tcp_port_is_given(self):
        """With a `tcp_port`, the reply is read from a TCP connection to
        that port instead of the UDP socket."""
        loop = asyncio.get_running_loop()
        radio = Radio.loopback()

        class Responder(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                async def reply_over_tcp():
                    request = await HTTPRequest.read_from((data, Endpoint.for_addr(addr)))
                    assert request is not None
                    tcp_port = int(request.headers["X-Reply-Port"])
                    _, writer = await asyncio.open_connection(str(LOOPBACK), tcp_port)
                    await HTTPResponse(HTTPStatus.OK).write_to(writer)
                    writer.close()
                    await writer.wait_closed()

                asyncio.get_running_loop().create_task(reply_over_tcp())

        responder_transport, _ = await loop.create_datagram_endpoint(Responder, local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(responder_transport):
            _, responder_port = responder_transport.get_extra_info("sockname")

            probe_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with contextlib.closing(probe_transport):
                _, tcp_port = probe_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            request = HTTPRequest("GET", ROOT, {"X-Reply-Port": str(tcp_port)})
            reply = await prompter.prompt_udp(request, Endpoint(LOOPBACK, responder_port), tcp_port=tcp_port)

            assert reply is not None
            assert reply.status == HTTPStatus.OK


class TestPrompterBroadcast:
    """`Prompter.broadcast()` sends a prompt datagram on every interface,
    gathering all their replies into the returned future."""

    async def test_sends_on_every_interface_and_gathers_replies(self):
        """Each interface's reply is gathered into the returned list."""
        loop = asyncio.get_running_loop()
        # `broadcast=None` means the datagram goes to the binding's own
        # address (this test's real listener) rather than `MULTICAST_GROUP`
        # - which still has to be a real multicast address, since joining
        # it as a group happens regardless of where the datagram is sent.
        radio = Radio(
            (
                Interface("eth0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),
                Interface("wlan0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),
            )
        )

        listener_transport, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(b"pong"), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(listener_transport):
            _, host_port = listener_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            reply_future = await prompter.broadcast(HTTPRequest("GET", ROOT), Endpoint(MULTICAST_GROUP, host_port))
            replies = await asyncio.wait_for(reply_future, timeout=2)

            assert len(replies) == 2
            assert all(reply is not None and reply[0] == b"pong" for reply in replies)

    async def test_a_callable_prompt_is_regenerated_for_every_interface(self):
        """A callable `prompt` is called again for each interface, with
        that interface's own local address - not just once, reused for
        every interface after the first."""
        loop = asyncio.get_running_loop()
        # `broadcast=None` means the datagram goes to the binding's own
        # address (this test's real listener) rather than `MULTICAST_GROUP`
        # - which still has to be a real multicast address, since joining
        # it as a group happens regardless of where the datagram is sent.
        radio = Radio(
            (
                Interface("eth0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),
                Interface("wlan0", {AF_INET: (Binding(LOOPBACK, broadcast=None),)}),
            )
        )

        received = []
        done = loop.create_future()

        class Responder(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                received.append((data, addr))
                if len(received) == 2 and not done.done():
                    done.set_result(None)

        listener_transport, _ = await loop.create_datagram_endpoint(Responder, local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(listener_transport):
            _, host_port = listener_transport.get_extra_info("sockname")

            def make_prompt(local: Endpoint) -> HTTPRequest:
                return HTTPRequest("GET", ROOT, {"X-Local": str(local)})

            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            _ = await prompter.broadcast(make_prompt, Endpoint(MULTICAST_GROUP, host_port))
            await asyncio.wait_for(done, timeout=2)

            assert len(received) == 2
            for data, addr in received:
                request = await HTTPRequest.read_from((data, Endpoint.for_addr(addr)))
                assert request is not None
                assert request.headers["X-Local"] == str(Endpoint.for_addr(addr))


class TestPrompterBroadcastPrompt:
    """`Prompter.broadcast_prompt()` sends a datagram prompt on every
    interface and streams back whatever replies arrive, over UDP or TCP."""

    async def test_streams_a_deserialized_reply_over_udp(self):
        """A reply sent back to the broadcasting socket's own address is
        deserialized and streamed."""
        loop = asyncio.get_running_loop()
        radio = Radio.loopback(broadcast=None)

        responder_transport, _ = await loop.create_datagram_endpoint(lambda: StaticReplyProtocol(bytes(HTTPResponse(HTTPStatus.OK))), local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(responder_transport):
            _, responder_port = responder_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            replies = await prompter.broadcast_prompt(HTTPRequest("GET", ROOT), Endpoint(MULTICAST_GROUP, responder_port))

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.status == HTTPStatus.OK

    async def test_streams_a_deserialized_reply_over_tcp_when_a_tcp_port_is_given(self):
        """With a `tcp_port`, replies are read from TCP connections to
        that port instead of the broadcasting UDP socket."""
        loop = asyncio.get_running_loop()
        radio = Radio.loopback(broadcast=None)

        class Responder(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                async def reply_over_tcp():
                    request = await HTTPRequest.read_from((data, Endpoint.for_addr(addr)))
                    assert request is not None
                    tcp_port = int(request.headers["X-Reply-Port"])
                    _, writer = await asyncio.open_connection(str(LOOPBACK), tcp_port)
                    await HTTPResponse(HTTPStatus.OK).write_to(writer)
                    writer.close()
                    await writer.wait_closed()

                asyncio.get_running_loop().create_task(reply_over_tcp())

        responder_transport, _ = await loop.create_datagram_endpoint(Responder, local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(responder_transport):
            _, responder_port = responder_transport.get_extra_info("sockname")

            probe_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with contextlib.closing(probe_transport):
                _, tcp_port = probe_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            request = HTTPRequest("GET", ROOT, {"X-Reply-Port": str(tcp_port)})
            replies = await prompter.broadcast_prompt(request, Endpoint(MULTICAST_GROUP, responder_port), tcp_port=tcp_port)

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.status == HTTPStatus.OK

    async def test_closes_the_tcp_connection_for_a_terminal_reply(self):
        """A reply with `Connection: close` closes the TCP connection it
        arrived on, same as `prompt_tcp()` does - checked from the reply
        sender's side, since that's a real explicit `close()`, not one
        racing the garbage collector (see the note on
        `test_leaves_the_connection_open_for_a_non_terminal_reply`)."""
        loop = asyncio.get_running_loop()
        radio = Radio.loopback(broadcast=None)
        saw_eof: asyncio.Future[bytes] = loop.create_future()

        class Responder(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                async def reply_over_tcp():
                    request = await HTTPRequest.read_from((data, Endpoint.for_addr(addr)))
                    assert request is not None
                    tcp_port = int(request.headers["X-Reply-Port"])
                    reader, writer = await asyncio.open_connection(str(LOOPBACK), tcp_port)
                    await HTTPResponse(HTTPStatus.OK, {"Connection": "close"}).write_to(writer)
                    saw_eof.set_result(await reader.read())
                    writer.close()
                    await writer.wait_closed()

                asyncio.get_running_loop().create_task(reply_over_tcp())

        responder_transport, _ = await loop.create_datagram_endpoint(Responder, local_addr=(str(LOOPBACK), 0))
        with contextlib.closing(responder_transport):
            _, responder_port = responder_transport.get_extra_info("sockname")

            probe_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with contextlib.closing(probe_transport):
                _, tcp_port = probe_transport.get_extra_info("sockname")

            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            request = HTTPRequest("GET", ROOT, {"X-Reply-Port": str(tcp_port)})
            replies = await prompter.broadcast_prompt(request, Endpoint(MULTICAST_GROUP, responder_port), tcp_port=tcp_port)

            async with replies.stream() as streamer:
                reply = await asyncio.wait_for(anext(aiter(streamer)), timeout=2)
                assert reply.status == HTTPStatus.OK

            assert await asyncio.wait_for(saw_eof, timeout=2) == b""


class TestQueueIterator:
    """`queue_iterator()` yields items from an `asyncio.Queue` as they
    arrive, stopping (without yielding it) once it sees a `None`
    sentinel."""

    async def test_yields_items_in_the_order_theyre_put(self):
        """Items come out in the same order they went in."""
        queue = asyncio.Queue()
        await queue.put("a")
        await queue.put("b")
        await queue.put(None)

        assert [item async for item in queue_iterator(queue)] == ["a", "b"]

    async def test_a_none_sentinel_stops_iteration_without_being_yielded(self):
        """A bare `None` ends iteration, rather than being yielded itself."""
        queue = asyncio.Queue()
        await queue.put(None)

        assert [item async for item in queue_iterator(queue)] == []
