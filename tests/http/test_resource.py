from gossip.http.predicate import StringPredicate
from gossip.http.resource import Resource, ResourceCollection
from gossip.internet.uri import URI
from gossip.network.serializer import BufferedReader

TARGET = URI.parse("/foo")


class TestResourceConstruction:
    """Building a `Resource` from its identifying URL, headers, and body."""

    def test_identifier_and_headers_are_stored(self):
        """`identifier` is stored as given; `headers` is case-insensitive."""
        resource = Resource(TARGET, {"Content-Type": "text/plain"}, BufferedReader.for_bytes(b""))
        assert resource.identifier == TARGET
        assert resource.headers["content-type"] == "text/plain"

    def test_body_is_used_exactly_as_given(self):
        """`body` is the same object passed in, not a copy."""
        body = BufferedReader.for_bytes(b"hello")
        resource = Resource(TARGET, {}, body)
        assert resource.body is body


class TestResourceReadBody:
    """`read_body()` - materializes a resource's body into a `Buffer`."""

    async def test_reads_the_whole_body(self):
        """Reads the entire body content into a single `Buffer`."""
        resource = Resource(TARGET, {}, BufferedReader.for_bytes(b"hello world"))
        assert await resource.read_body() == b"hello world"

    async def test_empty_body_reads_nothing(self):
        """An empty body reads back as empty."""
        resource = Resource(TARGET, {}, BufferedReader.for_bytes(b""))
        assert await resource.read_body() == b""


class TestResourceCollectionIsRepresentable:
    """`ResourceCollection.is_representable()` - runs each predicate
    against its matching request header."""

    def test_a_matched_header_returns_the_accepted_option_and_its_args(self):
        """A matching header value is paired with the accepted option."""
        collection = ResourceCollection({"Accept": StringPredicate(["text/plain"])})
        result = collection.is_representable({"Accept": "text/plain"})
        assert result == {"Accept": ("text/plain", {})}

    def test_a_rejected_header_returns_none_paired_with_an_empty_dict(self):
        """A non-matching header value returns a falsy option."""
        collection = ResourceCollection({"Accept": StringPredicate(["text/plain"])})
        result = collection.is_representable({"Accept": "application/json"})
        option, _ = result["Accept"]
        assert not option

    def test_a_header_not_present_in_the_request_is_omitted_entirely(self):
        """A predicate with no matching request header gets no entry."""
        collection = ResourceCollection({"Accept": StringPredicate(["text/plain"])})
        assert collection.is_representable({}) == {}

    def test_a_header_with_no_predicate_is_ignored(self):
        """A header the collection has no predicate for is skipped."""
        collection = ResourceCollection({"Accept": StringPredicate(["text/plain"])})
        result = collection.is_representable({"Host": "example.com"})
        assert result == {}
