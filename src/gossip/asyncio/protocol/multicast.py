import logging
import socket
import struct
from asyncio.protocols import DatagramProtocol
from asyncio.transports import BaseTransport
from typing import override

log = logging.getLogger(__name__)


class MulticastDatagramProtocol(DatagramProtocol):
    """A DatagramProtocol that can optionally join a multicast group."""

    """Dictates whether we'll use multicast (and join the given group), or
    unicast (if the group is `None`.)
    """
    group_address: str | None

    """Dictates which interface we'll join our multicast group with, to
    optionally filter packets for the interface.
    """
    interface_address: str | None

    """If the connection is over SSL or not."""
    over_ssl: bool

    def __init__(self, group_address: str | None = None, interface_address: str | None = None):
        # If non-`None`, we'll attempt to join the group with the given address
        # using the `IP_ADD_MEMBERSHIP` socket option.
        self.group_address = group_address

        # If non-`None`, we'll join under this interface address to filter only
        # for packets for a specific interface on the machine.
        self.interface_address = interface_address

    @override
    def connection_made(self, transport: BaseTransport):
        if self.group_address is not None:
            # Allow receiving multicast broadcasts
            log.debug("%s connected, joining multicast group %s", self.__class__.__name__, self.group_address)
            sock = transport.get_extra_info("socket")
            group = socket.inet_aton(str(self.group_address))

            if self.interface_address is not None:
                log.debug("%s filtering for interface %s", self.__class__.__name__, self.interface_address)
                # IP_ADD_MEMBERSHIP expects a 4-byte group address and a 4-byte interface address
                mreq = struct.pack("4s4s", group, socket.inet_aton(self.interface_address))

                # Tells the kernel: "Send all multicast traffic for this socket via 192.168.0.114"
                # interface = socket.inet_aton(str(self.interface_address))
                # sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, interface)
            else:
                log.debug("%s not filtering by interface", self.__class__.__name__)
                # Fallback to INADDR_ANY if no specific interface address is provided
                mreq = struct.pack("4sL", group, socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            # Allow loopback multicast packets to be received, so we can work
            # without any network connection.
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        self.over_ssl = transport.get_extra_info("sslcontext") is not None
