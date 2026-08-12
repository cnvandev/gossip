import pytest

from gossip.utils.multidict import CaseInsensitiveMultiDict, cistr


class TestCistr:
    """Whether `cistr` treats two strings as the same key purely by their
    casefolded content, for both equality and hashing."""

    def test_equal_ignores_case(self):
        """A `cistr` compares equal to another string with the same content
        in a different case, whether the other side is a `cistr` or a plain
        `str`."""
        assert cistr("Content-Type") == cistr("content-type")
        assert cistr("Content-Type") == "content-type"

    def test_hash_ignores_case(self):
        """Two `cistr`s with the same content in different cases hash the
        same, so they land in the same dict bucket."""
        assert hash(cistr("Content-Type")) == hash(cistr("content-type"))

    def test_not_equal_different_value(self):
        """Two `cistr`s with genuinely different content are not equal,
        regardless of casing."""
        assert cistr("Content-Type") != "content-length"


class TestCaseInsensitiveMultiDictAccess:
    """Reading and writing entries by key, regardless of the casing used to
    set or look them up."""

    def test_get_and_set_same_case(self):
        """A value set under one casing is retrievable under that exact
        casing."""
        headers = CaseInsensitiveMultiDict()
        headers["Content-Type"] = "text/html"
        assert headers["Content-Type"] == "text/html"

    def test_get_is_case_insensitive(self):
        """A value set under one casing is retrievable under any other
        casing of the same key."""
        headers = CaseInsensitiveMultiDict()
        headers["Content-Type"] = "text/html"
        assert headers["content-type"] == "text/html"
        assert headers["CONTENT-TYPE"] == "text/html"

    def test_contains_is_case_insensitive(self):
        """`in` matches a key regardless of casing, and correctly reports
        `False` for a key that was never set."""
        headers = CaseInsensitiveMultiDict()
        headers["Host"] = "example.com"
        assert "host" in headers
        assert "HOST" in headers
        assert "Accept" not in headers

    def test_construct_from_mapping_preserves_case_insensitivity(self):
        """Building a multidict from a plain mapping gives it the same
        case-insensitive lookup behavior as building it key-by-key."""
        headers = CaseInsensitiveMultiDict({"Host": "example.com"})
        assert headers["host"] == "example.com"

    def test_get_with_default_does_not_raise_or_mutate(self):
        """`.get()` behaves like a read: checking for a key that was never
        set shouldn't create it as a side effect."""
        headers = CaseInsensitiveMultiDict()
        assert headers.get("Accept", "fallback") == "fallback"
        assert "Accept" not in headers
        assert dict(headers) == {}

    def test_missing_key_subscript_raises_key_error(self):
        """Bare subscript access on a key that was never set raises
        `KeyError`, the same as a plain `dict`."""
        headers = CaseInsensitiveMultiDict()
        with pytest.raises(KeyError):
            headers["Accept"]
        assert "Accept" not in headers


class TestCaseInsensitiveMultiDictRepeatedWrites:
    """What happens when the same logical key is set more than once under
    different casing."""

    def test_last_write_wins_regardless_of_case(self):
        """The value returned for a repeatedly-set key is whatever was
        written most recently, no matter what casing each write used."""
        headers = CaseInsensitiveMultiDict()
        headers["Host"] = "first.example.com"
        headers["HOST"] = "second.example.com"
        assert headers["host"] == "second.example.com"
        assert len(headers) == 1

    def test_first_seen_casing_is_preserved_on_repeat_writes(self):
        """Even though the value follows the most recent write, the casing
        shown on iteration stays whatever casing was used the first time -
        a deliberate choice, not just an accident of `dict` internals."""
        headers = CaseInsensitiveMultiDict()
        headers["Host"] = "first.example.com"
        headers["HOST"] = "second.example.com"
        assert list(headers.keys()) == ["Host"]


class TestCaseInsensitiveMultiDictDeletion:
    """Removing an entry by key, regardless of the casing used to set or
    delete it."""

    def test_delete_with_same_case_it_was_set_with(self):
        """Deleting a header using the exact casing it was set with removes
        it."""
        headers = CaseInsensitiveMultiDict()
        headers["Content-Type"] = "text/html"
        del headers["Content-Type"]
        assert "Content-Type" not in headers

    def test_delete_is_case_insensitive(self):
        """Deleting a header works under a different casing than the one it
        was set with."""
        headers = CaseInsensitiveMultiDict()
        headers["Content-Type"] = "text/html"
        del headers["content-type"]
        assert "Content-Type" not in headers

    def test_delete_missing_key_raises_key_error(self):
        """Deleting a key that was never set raises `KeyError`, the same as
        a plain `dict`."""
        headers = CaseInsensitiveMultiDict()
        with pytest.raises(KeyError):
            del headers["Accept"]


class TestCaseInsensitiveMultiDictIteration:
    """What keys look like when read back out via iteration, `.keys()`,
    `.items()`, or a `dict()` copy - the internal case-insensitive `cistr`
    type must never leak past this boundary."""

    def test_iteration_yields_plain_str_not_cistr(self):
        """A key produced by iteration is a plain `str`, not the internal
        `cistr` it's stored as."""
        headers = CaseInsensitiveMultiDict({"Content-Type": "text/html"})
        (key,) = headers.keys()
        assert type(key) is str

    def test_dict_conversion_is_an_ordinary_case_sensitive_dict(self):
        """`dict(some_multidict)` produces a copy that behaves like a normal
        dict: a plain-string containment check finds an entry regardless of
        how it was hashed internally, which wouldn't hold if a `cistr` leaked
        into the copy instead of a plain `str`."""
        headers = CaseInsensitiveMultiDict({"Content-Length": "999"})
        headers_dict = dict(headers)
        assert "Content-Length" in headers_dict
        assert len(headers_dict) == 1
