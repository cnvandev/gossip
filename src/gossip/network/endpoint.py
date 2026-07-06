from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import NamedTuple, Self


class Endpoint(NamedTuple):
    """An endpoint, a combination of IP address and port."""

    address: IPv4Address | IPv6Address
    port: int

    def __str__(self) -> str:
        return f"{self.address}:{self.port}"

    @classmethod
    def for_addr(cls, address: tuple[str, int]) -> Self:
        return cls(ip_address(address[0]), address[1])

    @classmethod
    def parse(cls, s: str) -> Self:
        host, port = s.split(":")
        return cls(ip_address(host), int(port))
