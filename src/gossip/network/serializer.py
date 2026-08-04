from asyncio.streams import StreamReader, StreamWriter
from typing import Protocol, Self, SupportsBytes

from gossip.network.endpoint import Endpoint


class Serializable(SupportsBytes, Protocol):
    """Base class that defines serializability."""

    async def write_to(self, writer: StreamWriter) -> None:
        """Write ourselves to the stream via `bytes()`.

        This is the intentionally-dumb default implementation, it loads the
        serialization into memory so it might be inefficient, but for something
        that would fit into a UDP packet this is fine.

        Subclasses can override this to provide a more efficient implementation.
        """
        writer.write(bytes(self))
        await writer.drain()

    @classmethod
    async def read_from(cls, reader: StreamReader | tuple[bytes, Endpoint]) -> Self | None: ...
