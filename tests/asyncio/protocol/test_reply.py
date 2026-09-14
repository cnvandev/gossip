import asyncio
from contextlib import closing
from ipaddress import IPv4Address

import pytest

from gossip.asyncio.protocol.reply import DatagramReplyProtocol
from gossip.network.endpoint import Endpoint

from ...support.network import await_reply

LOOPBACK = IPv4Address("127.0.0.1")


class TestDatagramReplyProtocolInit:
    """Building a `DatagramReplyProtocol`."""

    async def test_defaults_to_the_running_event_loop(self):
        """Omitting `loop` still schedules `reply` on the loop that's
        actually running, not a disconnected one."""
        protocol = DatagramReplyProtocol()
        assert protocol.reply.get_loop() is asyncio.get_running_loop()


class TestDatagramReplyProtocolDatagramReceived:
    """`DatagramReplyProtocol.datagram_received()` resolves `reply` with
    the datagram's bytes and the sender's `Endpoint`."""

    async def test_resolves_reply_with_the_datagram_and_sender(self):
        """A real datagram arriving resolves `reply` with its bytes and
        the sender's endpoint."""
        loop = asyncio.get_running_loop()

        listen_transport, listener = await loop.create_datagram_endpoint(lambda: DatagramReplyProtocol(loop), local_addr=(str(LOOPBACK), 0))
        with closing(listen_transport):
            _, listen_port = listen_transport.get_extra_info("sockname")

            send_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
            with closing(send_transport):
                _, sender_port = send_transport.get_extra_info("sockname")
                send_transport.sendto(b"ping", (str(LOOPBACK), listen_port))

                data, sender = await await_reply(listener)
                assert data == b"ping"
                assert sender == Endpoint(LOOPBACK, sender_port)


class TestDatagramReplyProtocolErrorReceived:
    """`DatagramReplyProtocol.error_received()` fails `reply` with
    whatever error the socket reports."""

    async def test_fails_reply_with_a_real_connection_refused_error(self):
        """Sending to a closed port on loopback reports a real
        `ConnectionRefusedError` back through `reply` - not a fake or
        simulated one."""
        loop = asyncio.get_running_loop()

        # Bind and immediately close a socket, to get a port that's
        # definitely not listening.
        probe_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
        _, closed_port = probe_transport.get_extra_info("sockname")
        probe_transport.close()

        transport, protocol = await loop.create_datagram_endpoint(lambda: DatagramReplyProtocol(loop), remote_addr=(str(LOOPBACK), closed_port))
        with closing(transport):
            transport.sendto(b"ping")
            with pytest.raises(ConnectionRefusedError):
                await asyncio.wait_for(protocol.reply, timeout=2)


class TestDatagramReplyProtocolConnectionLost:
    """`DatagramReplyProtocol.connection_lost()` resolves `reply` with
    `None` on a clean close with nothing received, or fails it with the
    given error - but never clobbers a `reply` that's already resolved."""

    async def test_resolves_reply_with_none_on_a_clean_close_with_nothing_received(self):
        """Closing the transport with nothing ever received resolves
        `reply` with `None`, rather than leaving it pending forever."""
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(lambda: DatagramReplyProtocol(loop), local_addr=(str(LOOPBACK), 0))
        transport.close()

        assert await asyncio.wait_for(protocol.reply, timeout=2) is None

    async def test_a_clean_close_after_a_reply_already_arrived_leaves_it_alone(self):
        """Closing the transport after `reply` is already resolved with
        a real datagram doesn't clobber it with `None`."""
        loop = asyncio.get_running_loop()
        listen_transport, listener = await loop.create_datagram_endpoint(lambda: DatagramReplyProtocol(loop), local_addr=(str(LOOPBACK), 0))
        _, listen_port = listen_transport.get_extra_info("sockname")

        send_transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(str(LOOPBACK), 0))
        with closing(send_transport):
            send_transport.sendto(b"ping", (str(LOOPBACK), listen_port))
            data, _ = await await_reply(listener)
            assert data == b"ping"

        listen_transport.close()
        assert listener.reply.result() is not None

    async def test_fails_reply_with_the_given_error(self):
        """Given a real error, `reply` fails with that same error.

        There's no portable, legitimate socket operation that reliably
        makes a real transport call `connection_lost()` with an actual
        exception (unlike `error_received()`, which a real
        connection-refused ICMP does trigger) - so this calls the
        callback directly, exactly as the transport would."""
        protocol = DatagramReplyProtocol()
        error = OSError("network is unreachable")
        protocol.connection_lost(error)
        assert protocol.reply.exception() is error
