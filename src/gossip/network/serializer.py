from asyncio.streams import StreamReader, StreamWriter
from typing import Protocol, Self, SupportsBytes

from gossip.network.endpoint import Endpoint


class Serializable(SupportsBytes, Protocol):
    """Base class that defines serializability."""

    async def write_to(self, writer: StreamWriter) -> None: ...

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None: ...
