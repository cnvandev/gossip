from http import HTTPStatus
from ipaddress import IPv4Address

import pytest

from gossip.http.message import HTTPRequest, HTTPResponse
from gossip.internet.uri import URI
from gossip.network.endpoint import Endpoint
from gossip.network.prompter import Prompter
from gossip.network.radio import Radio

from ..support.asyncio import wait_closing
from ..support.network import free_tcp_port

LOOPBACK = IPv4Address("127.0.0.1")
ROOT = URI.parse("/")


class TestPromptSessionSend:
    """`PromptSession.send()` writes a prompt to the open connection,
    which stays open for more than one prompt/reply cycle as long as
    neither side ends it."""

    async def test_sends_a_second_prompt_down_the_same_connection(self):
        """A prompt sent from inside the `async for` loop, after a
        previous reply's been read, goes down the same connection - the
        server here only ever accepts one connection, and reads two
        requests off it."""

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
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            session = await prompter.prompt_tcp(HTTPRequest("GET", URI.parse("/one")), Endpoint(LOOPBACK, port))

            targets = []
            async for reply in session:
                targets.append(reply.headers["Test-Echo-Target"])
                if len(targets) == 1:
                    await session.send(HTTPRequest("GET", URI.parse("/two")))
                else:
                    break

            assert targets == ["/one", "/two"]

            session.close()
            await session.wait_closed()

    async def test_raises_if_the_previous_reply_hasnt_been_read(self):
        """`send()` raises if called again before the prior `send()`'s
        reply has been read - `prompt_tcp()` itself already sent one and
        left it unread, so a second `send()` here raises immediately."""

        async def on_connection(reader, _writer):
            await reader.read()

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            session = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))

            with pytest.raises(RuntimeError):
                await session.send(HTTPRequest("GET", ROOT))

            session.close()
            await session.wait_closed()

    async def test_raises_once_the_session_is_closed(self):
        """`send()` raises once the connection is closed, whether that
        happened on its own or by an explicit `close()`."""

        async def on_connection(reader, _writer):
            await reader.read()

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            session = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))
            session.close()
            await session.wait_closed()

            with pytest.raises(ConnectionError):
                await session.send(HTTPRequest("GET", ROOT))


class TestPromptSessionContextManager:
    """`async with` on a `PromptSession` closes its connection on exit."""

    async def test_closes_the_connection_on_exit(self):
        """The connection is closed once the `async with` block exits,
        even though its reply was never read."""

        async def on_connection(reader, writer):
            await HTTPRequest.read_from(reader)
            await HTTPResponse(HTTPStatus.OK).write_to(writer)

        radio = Radio.loopback()
        server = await radio.tcp_listen(on_connection)
        async with wait_closing(server):
            _, port = server.sockets[0].getsockname()
            prompter = Prompter(HTTPResponse.read_from, radio=radio)
            session = await prompter.prompt_tcp(HTTPRequest("GET", ROOT), Endpoint(LOOPBACK, port))

            async with session:
                pass

            assert session.writer.is_closing() is True
            assert await anext(session, None) is None
