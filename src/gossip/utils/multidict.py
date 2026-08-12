from collections import UserDict


class cistr(str):
    """A case-insensitive string, which matches & hashes using `.casefold()`.

    Used as a key for `CaseInsensitiveMultiDict`.
    """

    def __hash__(self):
        return hash(self.casefold())

    def __eq__(self, other):
        return self.casefold() == other.casefold()


class CaseInsensitiveMultiDict(UserDict):
    """A case-insensitive multi-dictionary.

    This is suitable for serializing/deserializing as repeated key-value pairs
    as used in HTTP headers and query strings.
    """

    def __contains__(self, key):
        return super().__contains__(cistr(key))

    def __setitem__(self, key, value):
        super().__setitem__(cistr(key), value)

    def __getitem__(self, key):
        return super().__getitem__(cistr(key))

    def __delitem__(self, key):
        super().__delitem__(cistr(key))

    def __iter__(self):
        """An iterator over the keys in this multi-dictionary.

        Yield plain `str` keys, not the internal `cistr`s they're stored
        as - `cistr`'s case-insensitive hash/eq only make sense inside this
        class. A `cistr` leaking out and landing in an ordinary `dict` or
        `set` alongside plain strings would silently fail to match them
        (e.g. `"Content-Length" in dict(some_multidict)` could be `False`
        even when that exact header is present), since `keys()`, `items()`,
        and `dict(this)` are all built on `__iter__`.
        """
        return (str(key) for key in self.data)


multidict = CaseInsensitiveMultiDict
