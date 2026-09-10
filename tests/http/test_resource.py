from asyncio import Future
from asyncio import run as run_async
from collections.abc import Buffer

from gossip.http.resource import Resource
from gossip.internet.uri import URI
from gossip.network.serializer import BufferedReader

TARGET = URI.parse("/foo")


class TestResourceConstruction:
    """Building a `Resource` from its identifying URL, headers, and body -
    requires a running event loop, since `trailers` is a real `Future`
    bound to one from the start."""

    def test_identifier_and_headers_are_stored(self):
        """The identifying URL is stored as given; headers normalize to a
        `multidict`, giving case-insensitive lookup regardless of what was
        passed in."""

        async def build() -> Resource:
            return Resource(TARGET, {"Content-Type": "text/plain"}, BufferedReader.for_bytes(b""))

        resource = run_async(build())
        assert resource.identifier == TARGET
        assert resource.headers["content-type"] == "text/plain"

    def test_body_is_used_exactly_as_given(self):
        """`body` isn't wrapped or bounded at all - it's the same object
        passed in, regardless of any `Content-Length` header."""

        async def build() -> tuple[Resource, BufferedReader]:
            body = BufferedReader.for_bytes(b"hello")
            resource = Resource(TARGET, {"Content-Length": "5"}, body)
            return resource, body

        resource, body = run_async(build())
        assert resource.body is body

    def test_trailers_is_a_future(self):
        """`trailers` is a real `asyncio.Future`, not a plain value."""

        async def build() -> Resource:
            return Resource(TARGET, {}, BufferedReader.for_bytes(b""))

        resource = run_async(build())
        assert isinstance(resource.trailers, Future)

    def test_trailers_is_never_resolved(self):
        """Nothing in `Resource` resolves `trailers` right now - how
        trailers should actually work here is still being figured out,
        so this is deliberately incomplete rather than wired up to a
        design that's about to change again. Draining `body` fully
        doesn't change that."""

        async def check() -> bool:
            resource = Resource(TARGET, {}, BufferedReader.for_bytes(b"hello"))
            await resource.read_body()
            return resource.trailers.done()

        assert run_async(check()) is False


class TestResourceReadBody:
    """Materializing a resource's body into a `Buffer`, via `read_body()` -
    just reads `body` to EOF, whatever `body` happens to be. A caller
    streaming a live body straight through (e.g. audio to speakers)
    wouldn't use this at all - it'd read `resource.body` directly."""

    def test_reads_the_whole_body(self):
        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {}, BufferedReader.for_bytes(b"hello world"))
            return await resource.read_body()

        assert run_async(read_it()) == b"hello world"

    def test_content_length_no_longer_bounds_anything(self):
        """A `Content-Length` header - even one shorter than what's
        actually on `body` - has no effect: `body` is read to its own
        EOF regardless, since nothing wraps it to enforce the header
        anymore."""

        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {"Content-Length": "5"}, BufferedReader.for_bytes(b"hello world"))
            return await resource.read_body()

        assert run_async(read_it()) == b"hello world"

    def test_empty_body_reads_nothing(self):
        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {}, BufferedReader.for_bytes(b""))
            return await resource.read_body()

        assert run_async(read_it()) == b""
