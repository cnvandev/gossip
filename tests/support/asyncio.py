"""Shared asyncio test helpers.

Not a test module - imported by tests that need to close something
that requires an awaited `wait_closed()`, not just a `close()` call.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol


class _WaitsToClose(Protocol):
    def close(self) -> None: ...
    async def wait_closed(self) -> None: ...


@asynccontextmanager
async def wait_closing[T: _WaitsToClose](closeable: T) -> AsyncIterator[T]:
    """Closes `closeable` on exit, awaiting `wait_closed()` too - unlike
    `contextlib.closing()`, for things (like `asyncio.Server`/
    `asyncio.StreamWriter`) where closing needs a wait, not just a call."""
    try:
        yield closeable
    finally:
        closeable.close()
        await closeable.wait_closed()
