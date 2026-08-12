from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import NamedTuple, Self


class Endpoint(NamedTuple):
    """An endpoint, a combination of IP address and port."""

    address: IPv4Address | IPv6Address
    port: int

    def __str__(self) -> str:
        """Render as `address:port`, bracketing the address per RFC 3986
        §3.2.2 (`[address]:port`) when it's IPv6 - otherwise `host:port`
        would be ambiguous with the address's own colons."""
        if isinstance(self.address, IPv6Address):
            return f"[{self.address}]:{self.port}"
        return f"{self.address}:{self.port}"

    @classmethod
    def for_addr(cls, address: tuple[str, int] | tuple[str, int, int, int]) -> Self:
        """Build from a raw socket address tuple: `(host, port)` for IPv4,
        or the 4-tuple `(host, port, flowinfo, scope_id)` `socket`/`asyncio`
        use for IPv6. Only the first two elements matter here."""
        return cls(ip_address(address[0]), address[1])

    @classmethod
    def parse(cls, s: str) -> Self:
        """Parse `address:port`, or `[address]:port` for IPv6 (RFC 3986
        §3.2.2) - brackets are required for IPv6 since an unbracketed
        address's own colons can't otherwise be told apart from the one
        separating it from the port."""
        if s.startswith("["):
            host, _, port = s[1:].partition("]:")
        else:
            host, _, port = s.partition(":")

        if not port:
            raise ValueError(f"Malformed endpoint, expected 'address:port' or '[address]:port': {s!r}")

        return cls(ip_address(host), int(port))
