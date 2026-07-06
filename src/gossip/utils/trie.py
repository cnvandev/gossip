import logging
from itertools import islice
from typing import Collection, Iterator, KeysView, MutableMapping

from typing_extensions import override

log = logging.getLogger(__name__)


class TrieNode[T](MutableMapping[Collection[str], T]):
    """A trie node for storing values collections of string keys, like paths."""

    branches: MutableMapping[str, "TrieNode[T]"]
    data: T | None

    def __init__(self, data: T | None = None) -> None:
        self.branches = dict()
        self.data = data

    @override
    def __hash__(self):
        return hash(tuple(self.branches.items()) + (self.data,))

    def __len__(self) -> int:
        return sum(len(branch) for branch in self.branches.values()) + (1 if self.data is not None else 0)

    def keys(self) -> KeysView[Collection[str]]:
        return KeysView(tuple((step,) + tuple(stuff) for step, branch_subtree in self.branches.items() for stuff in branch_subtree.keys()))

    def __iter__(self) -> Iterator[Collection[str]]:
        return iter(self.keys())

    def __repr__(self) -> str:
        return repr(self.branches) + f"(data={self.data})"

    def __setitem__(self, key: Collection[str], value: T) -> None:
        current = self
        # Descent through the node graph, adding nodes as needed,
        # and storing the value in the leaves.
        for step in key:
            if step not in current.branches:
                current.branches[step] = TrieNode[T]()
            current = current.branches[step]
        current.data = value

    def __getitem__(self, key: Collection[str]) -> T:
        current = self
        for step in key:
            if step not in current.branches:
                raise KeyError(f"{key} not found")
            else:
                # Any candidates that match the node pass through
                current = current.branches[step]

        # We can follow the path, but only leaf nodes have data.
        if current.data is not None:
            return current.data
        else:
            raise KeyError(f"{key} not found")

    def __delitem__(self, key: Collection[str]) -> None:
        current = self
        path, name = islice(key, len(key) - 1, None)
        for step in path:
            if step not in current.branches:
                # Not present in our data.
                return
            current = current.branches[step]
        del current.branches[name]


trie = TrieNode
