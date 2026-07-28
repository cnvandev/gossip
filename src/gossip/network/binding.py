import asyncio
import ipaddress
import logging
from asyncio import Server
from asyncio.streams import StreamReader, StreamWriter
from asyncio.transports import DatagramTransport
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from socket import IPPROTO_UDP
from typing import Any, Self

from gossip.asyncio.protocol.callback import DatagramCallbackProtocol
from gossip.asyncio.protocol.reply import DatagramReplyProtocol
from gossip.network.endpoint import Endpoint

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Binding:
    """The address bound to an interface.

    It encapsulates the address itslf, the netmask, and any peer/broadcast
    addresses. There can be multiple for any given interface, even within the
    same address family."""

    addr: IPv4Address | IPv6Address
    netmask: IPv4Network | IPv6Network | None = None
    peer: IPv4Address | IPv6Address | None = None
    broadcast: IPv4Address | IPv6Address | None = None

    @property
    def address(self):
        """Yes, this is just so we can call `binding.address`"""
        return self.addr

    async def tcp_send(self, remote: Endpoint, local_port: int = 0) -> tuple[StreamReader, StreamWriter]:
        """Send a TCP message to the specified address/port."""
        return await asyncio.open_connection(
            str(remote.address),
            remote.port,
            local_addr=(str(self.address), local_port),
        )

    async def tcp_listen(self, callback: Callable[[StreamReader, StreamWriter], Awaitable[None]], port: int | None = None) -> Server:
        """Open a server on every address provided."""
        if port is None:
            return await asyncio.start_server(callback, str(self.address))
        else:
            return await asyncio.start_server(callback, str(self.address), port=port)

    async def udp_send(self, address: Endpoint) -> tuple[DatagramTransport, DatagramReplyProtocol]:
        """Send a UDP messages to an address."""
        loop = asyncio.get_running_loop()

        return await loop.create_datagram_endpoint(
            lambda: DatagramReplyProtocol(loop=loop),
            local_addr=str(self.address),
            remote_addr=(str(address[0]), address[1]),
            proto=IPPROTO_UDP,
        )

    async def udp_broadcast(self, group_address: IPv4Address | IPv6Address, port: int = 0) -> tuple[DatagramTransport, DatagramReplyProtocol]:
        """Send a UDP message on this binding."""
        loop = asyncio.get_running_loop()

        def factory():
            return DatagramReplyProtocol(loop, str(group_address), str(self.address))

        # The remote address is the group address, if broadcast is available.
        # Otherwise, we'll bind to our own address and multicast locally.
        remote_address = str(group_address) if self.broadcast is not None else str(self.address)

        # We don't need to bind to our own address for multicast; the protocol
        # will set the multicast interface address.
        return await loop.create_datagram_endpoint(
            factory,
            # local_addr=(str(self.address), 0),
            remote_addr=(remote_address, port),
            proto=IPPROTO_UDP,
            reuse_port=True,
            allow_broadcast=True,
        )

    async def udp_listen(self, callback: Callable[[bytes, IPv4Address | IPv6Address | None, Endpoint, DatagramTransport], Coroutine[Any, Any, None]], port: int, group_address: IPv4Address | IPv6Address | None = None, factory: Callable[[], DatagramCallbackProtocol] | None = None) -> tuple[DatagramTransport, DatagramCallbackProtocol]:
        """Listen for UDP messages on this binding."""
        loop = asyncio.get_running_loop()

        if factory is None:
            address_string = str(group_address) if group_address is not None else None

            def binding_factory():
                return DatagramCallbackProtocol(
                    callback,
                    loop=loop,
                    group_address=address_string,
                    interface_address=str(self.address),
                )

            factory = binding_factory

        if group_address is not None:
            local_addr = (str(group_address), port)
        else:
            local_addr = (str(self.address), port) if port is not None else str(self.address)

        return await loop.create_datagram_endpoint(
            factory,
            local_addr=local_addr,
            proto=IPPROTO_UDP,
            reuse_port=True,
            allow_broadcast=True,
        )

    @classmethod
    def from_ifaddresses(cls, address_dict: Mapping[str, str]) -> Self:
        kwargs = {}
        for arg in ("addr", "peer", "broadcast"):
            if arg in address_dict:
                kwargs[arg] = ipaddress.ip_address(address_dict.get(arg, ""))

        # netmask is an IP network address
        if "netmask" in address_dict:
            netmask_str = address_dict.get("netmask", "")
            kwargs["netmask"] = ipaddress.ip_network(netmask_str)

        return cls(**kwargs)
