from collections import UserDict
from collections.abc import Iterator
from typing import override


class cistr(str):
    """A case-insensitive string, which matches & hashes using `.casefold()`.

    Used as a key for `CaseInsensitiveMultiDict`.
    """

    @override
    def __hash__(self) -> int:
        return hash(self.casefold())

    @override
    def __eq__(self, other: object) -> bool:
        if isinstance(other, cistr):
            return self.casefold() == other.casefold()
        elif isinstance(other, str):
            return self == cistr(other)
        else:
            return False


class CaseInsensitiveMultiDict(UserDict[str, str]):
    """A case-insensitive multi-dictionary.

    This is suitable for serializing/deserializing as repeated key-value pairs
    as used in HTTP headers and query strings.
    """

    @override
    def __contains__(self, key: object) -> bool:
        return super().__contains__(cistr(key))

    @override
    def __setitem__(self, key: str, value: str) -> None:
        super().__setitem__(cistr(key), value)

    @override
    def __getitem__(self, key: str) -> str:
        return super().__getitem__(cistr(key))

    @override
    def __delitem__(self, key: str) -> None:
        super().__delitem__(cistr(key))

    @override
    def __iter__(self) -> Iterator[str]:
        """An iterator over the keys in this multi-dictionary.

        Yield plain `str` keys, not the internal `cistr`s they're stored
        as - `cistr`'s case-insensitive hash/eq only make sense inside this
        class. A `cistr` leaking out and landing in an ordinary `dict` or
        `set` alongside plain strings would silently fail to match them.
        """
        return (str(key) for key in self.data)


multidict = CaseInsensitiveMultiDict
