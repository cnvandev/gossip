import asyncio
import logging
from asyncio import Server
from asyncio.streams import StreamReader, StreamWriter
from asyncio.transports import DatagramTransport
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from socket import IPPROTO_UDP
from typing import Any, Awaitable, Callable, Coroutine, Generator, Mapping, Self

import netifaces

from gossip.asyncio.protocol.callback import DatagramCallbackProtocol
from gossip.asyncio.protocol.reply import DatagramReplyProtocol
from gossip.network.binding import Binding
from gossip.network.endpoint import Endpoint

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Interface:
    """An networking interface on a device, bound to any number of addresses."""

    name: str
    bindings: Mapping[int, tuple[Binding, ...]]

    async def tcp_send(self, remote: Endpoint) -> tuple[StreamReader, StreamWriter]:
        """Send a TCP message to the specified address/port."""
        return await asyncio.open_connection(str(remote.address), remote.port)

    async def tcp_listen(self, callback: Callable[[StreamReader, StreamWriter], Awaitable[None] | None], port: int | None = None) -> Server:
        """Listen for TCP connections on every address we can."""
        # `start_server` can handle a list of addresses to bind to, so we can
        # just pass that to listen on all provided interfaces.
        addresses = tuple(str(binding.address) for bindings in self.bindings.values() for binding in bindings)

        if port is None:
            return await asyncio.start_server(callback, addresses)
        else:
            return await asyncio.start_server(callback, addresses, port=port)

    async def udp_send(self, endpoint: Endpoint) -> tuple[DatagramTransport, DatagramReplyProtocol]:
        """Send a UDP messages to an address-port pair."""
        loop = asyncio.get_running_loop()
        return await loop.create_datagram_endpoint(
            lambda: DatagramReplyProtocol(loop=loop),
            remote_addr=(str(endpoint.address), endpoint.port),
            proto=IPPROTO_UDP,
        )

    async def udp_broadcast(self, group_address: IPv4Address | IPv6Address, port: int = 0) -> tuple[DatagramTransport, DatagramReplyProtocol]:
        # The OS will choose which interface to broadcast on based on the bound
        # IP address, or it'll choose whichever is easiest for the OS. We want
        # to make sure we use this interface, so we'll choose one of our binding
        # addresses.
        # Which one doesn't really matter, it just needs to be one bound to this
        # interface, and it should be the best one to let responders use for
        # their destination addresses. So we'll choose the longest netmask
        # prefix.
        viable = (binding for bindings in self.bindings.values() for binding in bindings)

        def order(binding: Binding) -> int:
            if binding.netmask is None:
                return 0
            else:
                return binding.netmask.prefixlen

        sorted_addresses = sorted(viable, key=order, reverse=True)
        log.debug("Starting broadcast from %s on interface `%s`.", sorted_addresses[0].address, self.name)
        return await sorted_addresses[0].udp_broadcast(group_address, port=port)

    async def udp_listen(self, callback: Callable[[bytes, Endpoint, DatagramTransport], Coroutine[Any, Any, None]], port: int, group_address: IPv4Address | IPv6Address | None = None, factory: Callable[[], DatagramCallbackProtocol] | None = None) -> tuple[DatagramTransport, DatagramCallbackProtocol]:
        loop = asyncio.get_running_loop()

        # `create_datagram_endpoint()` doesn't take a list of addresses, but we
        # kind of have to? I don't know, I'm using the first available one but I
        # should look into this more - there's probably a reason it doesn't take
        # a list. Maybe I just have to create a bunch of them here...?
        addresses = tuple(str(binding.address) for bindings in self.bindings.values() for binding in bindings)
        address_string = str(group_address) if group_address is not None else None

        if factory is None:

            def interface_factory():
                return DatagramCallbackProtocol(
                    callback,
                    loop=loop,
                    group_address=address_string,
                    interface_address=addresses[0],
                )

            factory = interface_factory

        if group_address is not None:
            log.debug("Group listen from %s to %s on port %d", addresses[0], group_address, port)
            return await loop.create_datagram_endpoint(
                factory,
                local_addr=("0.0.0.0", port),
                proto=IPPROTO_UDP,
                reuse_port=True,
                allow_broadcast=True,
            )
        else:
            log.debug("Unicast listen on port %d as %s", port, addresses[0])
            return await loop.create_datagram_endpoint(
                factory,
                local_addr=(addresses[0], port),
                proto=IPPROTO_UDP,
                reuse_port=True,
            )

    def addresses(self) -> Generator[IPv4Address | IPv6Address]:
        """All IP addresses bound to this interface."""
        return (binding.address for bindings in self.bindings.values() for binding in bindings)

    @classmethod
    def from_netifaces(cls, interface_name: str, address_families: tuple[int, ...]) -> Self:
        ifaddresses = netifaces.ifaddresses(interface_name)

        # The order of the binding dictionary matters, we'll use that as the
        # preference order when choosing addresses.
        bindings: dict[int, tuple[Binding, ...]] = dict()
        for family in address_families:
            bindings[family] = tuple(Binding.from_ifaddresses(addresses) for addresses in ifaddresses[family])

        return cls(interface_name, bindings)
