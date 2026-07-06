import socket
from ipaddress import ip_address


def resolve_ip(hostname):
    return tuple(
        map(
            ip_address,
            (
                i[4][0]
                for i in socket.getaddrinfo(hostname, 0)
                # ignore duplicate addresses with other socket types
                if i[1] is socket.SocketKind.SOCK_RAW
            ),
        )
    )
