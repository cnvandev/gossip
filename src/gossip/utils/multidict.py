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

    def __missing__(self, key):
        value = ()
        self.data[key] = value
        return value

    def __contains__(self, key):
        return super().__contains__(cistr(key))

    def __setitem__(self, key, value):
        super().__setitem__(cistr(key), value)

    def __getitem__(self, key):
        return super().__getitem__(cistr(key))


multidict = CaseInsensitiveMultiDict
