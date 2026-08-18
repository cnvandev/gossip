from asyncio import Future, StreamReader, sleep
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

    def test_trailers_is_a_future(self):
        """`trailers` is a real `asyncio.Future`, not a plain value - it's
        meant to be `await`ed or given a done callback, not read
        synchronously."""

        async def build() -> Resource:
            return Resource(TARGET, {}, BufferedReader.for_bytes(b""))

        resource = run_async(build())
        assert isinstance(resource.trailers, Future)


class TestResourceTrailersWithoutContentLength:
    """Without a `Content-Length`, `body` is used as given (unbounded), and
    `trailers` carries whatever value was passed at construction - resolved
    once `read_body()` drains `body` to genuine EOF."""

    def test_pending_before_the_body_is_drained(self):
        """A body with unread data still behind it means `trailers` isn't
        resolved yet.

        Uses a real `StreamReader`, fed with some data but never EOF'd,
        rather than a `BufferedReader` - an already fully-available source
        lets the pump's read calls resolve without ever suspending, so its
        whole loop (and the resolution) runs eagerly in one step with
        nothing left to observe as "pending"."""

        async def check() -> bool:
            source = StreamReader()
            source.feed_data(b"hello")
            resource = Resource(TARGET, {}, source, {"X-Checksum": "abc"})
            # Let the pump's task take its first step: it drains the 5
            # available bytes, then genuinely suspends waiting for more,
            # since the source was never EOF'd.
            await sleep(0)
            return resource.trailers.done()

        assert run_async(check()) is False

    def test_resolves_once_read_body_drains_it_to_eof(self):
        """Once `read_body()` has read the body all the way to EOF,
        `trailers` resolves with the value given at construction."""

        async def read_it() -> dict[str, str]:
            resource = Resource(TARGET, {}, BufferedReader.for_bytes(b"hello"), {"X-Checksum": "abc"})
            await resource.read_body()
            return dict(await resource.trailers)

        assert run_async(read_it()) == {"X-Checksum": "abc"}

    def test_resolved_immediately_for_an_already_empty_body(self):
        """An already-empty body is already at EOF, so `trailers` -
        defaulting to empty when none are given - resolves right away, with
        no `read_body()` call needed."""

        async def build() -> Resource:
            return Resource(TARGET, {}, BufferedReader.for_bytes(b""))

        resource = run_async(build())
        assert resource.trailers.done()
        assert dict(resource.trailers.result()) == {}


class TestResourceTrailersWithContentLength:
    """A valid `Content-Length` makes `body` a `BoundedReader` that cuts
    off at exactly that many bytes - and `trailers` resolves to empty the
    moment it does, since `Content-Length` and trailers are mutually
    exclusive in HTTP (RFC 9112 §6.3): there's provably nothing left to
    read as trailers here, regardless of what was passed in."""

    def test_resolves_to_empty_even_when_trailers_were_given(self):
        """Whatever `trailers` value was passed at construction is
        discarded - a Content-Length-bounded body can't have real
        trailers, so resolving to anything else would be a lie."""

        async def read_it() -> dict[str, str]:
            resource = Resource(TARGET, {"Content-Length": "5"}, BufferedReader.for_bytes(b"hello"), {"X-Checksum": "abc"})
            await resource.read_body()
            return dict(await resource.trailers)

        assert run_async(read_it()) == {}

    def test_resolves_even_when_the_body_is_read_directly(self):
        """The cutoff and resolution come from the `BoundedReader`'s own
        background pump, not from `read_body()` - so trailers resolve even
        for a caller that reads `resource.body` directly and never calls
        `read_body()` at all."""

        async def read_it() -> dict[str, str]:
            resource = Resource(TARGET, {"Content-Length": "5"}, BufferedReader.for_bytes(b"hello"))
            await resource.body.read()
            return dict(await resource.trailers)

        assert run_async(read_it()) == {}

    def test_resolves_immediately_for_content_length_zero(self):
        """A Content-Length of exactly 0 needs no read at all - `body` is
        already empty and at EOF, so `trailers` resolves right away."""

        async def build() -> Resource:
            return Resource(TARGET, {"Content-Length": "0"}, BufferedReader.for_bytes(b"hello"))

        resource = run_async(build())
        assert resource.trailers.done()
        assert dict(resource.trailers.result()) == {}

    def test_pending_until_the_bound_is_reached(self):
        """Before the `BoundedReader` has actually pumped its full limit,
        `trailers` is still pending.

        Uses a real `StreamReader`, fed with fewer bytes than the bound
        and never EOF'd, rather than a `BufferedReader` - an already
        fully-available source lets the pump's read calls resolve without
        ever suspending, so its whole loop (and the resolution) runs
        eagerly in one step with nothing left to observe as "pending"."""

        async def check() -> bool:
            source = StreamReader()
            source.feed_data(b"hel")
            resource = Resource(TARGET, {"Content-Length": "5"}, source)
            # Let the pump's task take its first step: it drains the 3
            # available bytes, then genuinely suspends waiting for the
            # rest, since none of it has arrived (and no EOF either).
            await sleep(0)
            return resource.trailers.done()

        assert run_async(check()) is False


class TestResourceReadBody:
    """Materializing a resource's body into a `Buffer`, via `read_body()` -
    for a caller that wants the whole body as bytes and can wait for it.
    A caller streaming an unbounded body straight through (e.g. audio to
    speakers) wouldn't use this at all - it'd read `resource.body`
    directly."""

    def test_reads_exactly_content_length_bytes(self):
        """A Content-Length header bounds `body` to an exact-length read,
        even though there's more behind it on the stream."""

        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {"Content-Length": "5"}, BufferedReader.for_bytes(b"hello world"))
            return await resource.read_body()

        assert run_async(read_it()) == b"hello"

    def test_missing_content_length_reads_until_eof(self):
        """A missing Content-Length doesn't mean there's no body - it means
        the length is unknown, possibly unbounded (e.g. read-until-close).
        `read_body()` reads until EOF rather than declining, trusting the
        source to end the transfer by closing."""

        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {}, BufferedReader.for_bytes(b"leftover-bytes"))
            return await resource.read_body()

        assert run_async(read_it()) == b"leftover-bytes"

    def test_malformed_content_length_also_reads_until_eof(self):
        """A non-numeric Content-Length is just as unusable for bounding a
        read as a missing one - it doesn't crash, it's treated the same
        way: read until EOF."""

        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {"Content-Length": "notanumber"}, BufferedReader.for_bytes(b"unbounded-data"))
            return await resource.read_body()

        assert run_async(read_it()) == b"unbounded-data"

    def test_content_length_zero_reads_nothing(self):
        """A Content-Length of exactly 0 means an already-empty body -
        nothing to read, even though the underlying source has more."""

        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {"Content-Length": "0"}, BufferedReader.for_bytes(b"hello"))
            return await resource.read_body()

        assert run_async(read_it()) == b""

    def test_source_ending_early_yields_whatever_arrived(self):
        """A source that closes before delivering the declared
        Content-Length isn't treated as an error - `read_body()` returns
        whatever partial data did arrive, same as the underlying
        `BoundedReader` would for any other caller."""

        async def read_it() -> Buffer | None:
            resource = Resource(TARGET, {"Content-Length": "999"}, BufferedReader.for_bytes(b"short"))
            return await resource.read_body()

        assert run_async(read_it()) == b"short"
