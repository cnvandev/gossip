import asyncio
import logging
from asyncio import Server
from asyncio.streams import StreamReader, StreamWriter
from asyncio.transports import DatagramTransport
from collections.abc import Awaitable, Callable, Coroutine, Generator, Mapping
from ipaddress import IPv4Address, IPv6Address
from socket import IPPROTO_UDP
from typing import Any, Self

import netifaces
from netifaces import AF_INET  # , AF_INET6

from gossip.asyncio.protocol.callback import DatagramCallbackProtocol
from gossip.asyncio.protocol.reply import DatagramReplyProtocol
from gossip.network.endpoint import Endpoint
from gossip.network.interface import Interface

log = logging.getLogger(__name__)


# These are the interfaces and address families supported by this radio.
INTERFACES = ("en", "lo")
ADDRESS_FAMILIES = (AF_INET,)  # AF_INET6)


class Radio:
    """Opens sockets suitable for applications which need to listen for and send
    messages, on both TCP & UDP."""

    # The list of addresses used on each interface.
    interfaces: Mapping[str, Interface]

    def __init__(self, interfaces: tuple[Interface, ...]):
        self.interfaces = {interface.name: interface for interface in interfaces}

    async def tcp_listen(self, callback: Callable[[StreamReader, StreamWriter], Awaitable[None]], port: int | None = None) -> Server:
        """Listen for TCP connections on every address we can."""
        return await asyncio.start_server(callback, port=port)

    async def tcp_send(self, remote: Endpoint) -> tuple[StreamReader, StreamWriter]:
        """Send a TCP message to the specified address/port."""
        return await asyncio.open_connection(str(remote.address), remote.port)

    async def udp_listen(self, callback: Callable[[bytes, Endpoint, DatagramTransport], Coroutine[Any, Any, None]], port: int = 0, group_address: IPv4Address | IPv6Address | None = None) -> list[tuple[DatagramTransport, DatagramCallbackProtocol]]:
        """Listen for UDP messages on all interfaces."""
        listeners = (
            interface.udp_listen(
                callback,
                port,
                group_address=group_address,
            )
            for interface in self.interfaces.values()
        )
        return await asyncio.gather(*listeners)

    async def udp_broadcast(self, group_address: IPv4Address | IPv6Address, port: int = 0) -> list[tuple[DatagramTransport, DatagramReplyProtocol]]:
        """Broadcast on all available interfaces."""
        broadcasts = (interface.udp_broadcast(group_address, port=port) for interface in self.interfaces.values())
        return await asyncio.gather(*map(asyncio.create_task, broadcasts))

    async def udp_send(self, endpoint: Endpoint) -> tuple[DatagramTransport, DatagramReplyProtocol]:
        """Send a UDP messages to an address-port pair."""
        loop = asyncio.get_running_loop()
        return await loop.create_datagram_endpoint(
            lambda: DatagramReplyProtocol(loop=loop),
            remote_addr=(str(endpoint.address), endpoint.port),
            proto=IPPROTO_UDP,
        )

    def addresses(self) -> Generator[IPv4Address | IPv6Address]:
        """All IP addresses bound to this radio."""
        return (address for interface in self.interfaces.values() for address in interface.addresses())

    @classmethod
    def from_netifaces(cls, interfaces: tuple[str, ...] = INTERFACES, address_families: tuple[int, ...] = ADDRESS_FAMILIES) -> Self:
        # First, we'll load all the interfaces and filter for supported prefixes
        interface_set = set(interfaces)
        useful_interfaces = {i for i in netifaces.interfaces() if i.rstrip("0123456789") in interface_set}

        # We only want addressable interfaces for the address families we can
        # address on, IPv4 and IPv6 (but not link addresses).
        addresses = {interface: netifaces.ifaddresses(interface) for interface in useful_interfaces}
        addressable_interfaces = {interface: interface_addresses for interface, interface_addresses in addresses.items() if any(family in interface_addresses for family in address_families)}
        return cls(tuple(Interface.from_netifaces(interface, address_families) for interface in addressable_interfaces))
