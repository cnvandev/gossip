import pytest

from gossip.http.resource import ResourceCollection
from gossip.internet.predicate import StringPredicate
from gossip.internet.uri import URI

from ..support.resources import InMemoryResource

TARGET = URI.parse("/foo")


class _RepresentOnly(ResourceCollection):
    """A `ResourceCollection` that overrides nothing but the required
    `represent()` - the least any resource can support."""

    async def represent(self, exact_uri, constraints):
        raise NotImplementedError


class _WithWrite(_RepresentOnly):
    async def write(self, exact_uri, constraints, request_body):
        raise NotImplementedError


class _WithPatch(_RepresentOnly):
    async def patch(self, exact_uri, constraints, patch):
        raise NotImplementedError


class _WithDelete(_RepresentOnly):
    async def delete(self, exact_uri, constraints):
        raise NotImplementedError


class _FullyWritable(_RepresentOnly):
    async def write(self, exact_uri, constraints, request_body):
        raise NotImplementedError

    async def patch(self, exact_uri, constraints, patch):
        raise NotImplementedError

    async def delete(self, exact_uri, constraints):
        raise NotImplementedError


class TestResourceCollectionIsRepresentable:
    """`ResourceCollection.is_representable()` - runs each predicate
    against its matching request header."""

    def test_a_matched_header_returns_the_accepted_option_and_its_args(self):
        """A matching header value is paired with the accepted option."""
        collection = InMemoryResource(predicates={"Accept": StringPredicate(["text/plain"])})
        result = collection.is_representable({"Accept": "text/plain"})
        assert result == {"Accept": ("text/plain", {})}

    def test_a_rejected_header_returns_none_paired_with_an_empty_dict(self):
        """A non-matching header value returns a falsy option."""
        collection = InMemoryResource(predicates={"Accept": StringPredicate(["text/plain"])})
        result = collection.is_representable({"Accept": "application/json"})
        option, _ = result["Accept"]
        assert not option

    def test_a_header_not_present_in_the_request_is_omitted_entirely(self):
        """A predicate with no matching request header gets no entry."""
        collection = InMemoryResource(predicates={"Accept": StringPredicate(["text/plain"])})
        assert collection.is_representable({}) == {}

    def test_a_header_with_no_predicate_is_ignored(self):
        """A header the collection has no predicate for is skipped."""
        collection = InMemoryResource(predicates={"Accept": StringPredicate(["text/plain"])})
        result = collection.is_representable({"Host": "example.com"})
        assert result == {}


class TestResourceCollectionSubcollections:
    """`ResourceCollection.subcollections()` - the default implementation
    has no subcollections of its own."""

    def test_defaults_to_empty(self):
        """With nothing overridden, there are no subcollections."""
        assert _RepresentOnly().subcollections() == {}


class TestResourceCollectionOptions:
    """`ResourceCollection.options()` derives its `Allow` header from
    which methods a subclass actually overrides, rather than needing
    each subclass to spell it out."""

    async def test_only_represent_allows_only_the_universal_methods(self):
        """With nothing else overridden, only the methods every resource
        supports regardless of what it implements are allowed."""
        options = await _RepresentOnly().options(TARGET, {})
        assert options == {"Allow": "GET, HEAD, OPTIONS, CONNECT, TRACE"}

    async def test_an_overridden_write_allows_put_too(self):
        """Overriding `write()` adds `PUT`."""
        options = await _WithWrite().options(TARGET, {})
        assert options == {"Allow": "GET, HEAD, OPTIONS, CONNECT, TRACE, PUT"}

    async def test_an_overridden_patch_allows_patch_too(self):
        """Overriding `patch()` adds `PATCH`."""
        options = await _WithPatch().options(TARGET, {})
        assert options == {"Allow": "GET, HEAD, OPTIONS, CONNECT, TRACE, PATCH"}

    async def test_an_overridden_delete_allows_delete_too(self):
        """Overriding `delete()` adds `DELETE`."""
        options = await _WithDelete().options(TARGET, {})
        assert options == {"Allow": "GET, HEAD, OPTIONS, CONNECT, TRACE, DELETE"}

    async def test_every_method_overridden_allows_everything(self):
        """Overriding every optional method allows every one of them."""
        options = await _FullyWritable().options(TARGET, {})
        assert options == {"Allow": "GET, HEAD, OPTIONS, CONNECT, TRACE, PUT, PATCH, DELETE"}


class TestResourceCollectionWrite:
    """`ResourceCollection.write()` - the default implementation raises,
    for a resource that doesn't support being written to."""

    async def test_raises_when_not_overridden(self):
        """A resource that hasn't implemented `write()` raises rather
        than silently doing nothing."""
        with pytest.raises(NotImplementedError):
            await _RepresentOnly().write(TARGET, {}, None)


class TestResourceCollectionDelete:
    """`ResourceCollection.delete()` - the default implementation
    raises, for a resource that doesn't support being deleted."""

    async def test_raises_when_not_overridden(self):
        """A resource that hasn't implemented `delete()` raises rather
        than silently doing nothing."""
        with pytest.raises(NotImplementedError):
            await _RepresentOnly().delete(TARGET, {})


class TestResourceCollectionPatch:
    """`ResourceCollection.patch()` - the default implementation
    raises, for a resource that doesn't support being patched."""

    async def test_raises_when_not_overridden(self):
        """A resource that hasn't implemented `patch()` raises rather
        than silently doing nothing."""
        with pytest.raises(NotImplementedError):
            await _RepresentOnly().patch(TARGET, {}, None)
