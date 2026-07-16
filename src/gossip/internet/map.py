import logging
from pathlib import PurePosixPath
from typing import Iterator, KeysView, Mapping

from gossip.internet.uri import URI
from gossip.utils.trie import TrieNode

log = logging.getLogger(__name__)


class URIMap[T](Mapping[URI, T]):
    """A routing table; a map of `URI`s to whatever they target.

    It internally uses a `gossip.utils.trie` to key on `URI`s along the domains
    & paths for easier search.
    """

    trie: TrieNode[TrieNode[T]]

    def __init__(self, data: Mapping[URI, T] | None = None):
        self.trie = TrieNode[TrieNode[T]]()
        if data is None:
            data = dict()

        for key, value in data.items():
            self[key] = value

    def __len__(self) -> int:
        return len(self.trie)

    def __iter__(self) -> Iterator[URI]:
        return iter(self.keys())

    def keys(self) -> KeysView[URI]:
        output = {tuple(domain_parts): tuple(key) for domain_parts, path_trie in self.trie.items() for key in path_trie.keys()}
        log.info("OUTPUT: %r", output)
        return KeysView({URI.parse(".".join(reversed(domain_parts)) + "/" + "/".join(path_parts)) for domain_parts, path_parts in output.items()})

    def __setitem__(self, key: URI, value: T) -> None:
        domain_split = key.netloc.split(".")
        domain_key = tuple(reversed(domain_split))

        domain_trie = self.trie.get(domain_key)
        if not domain_trie:
            domain_trie = TrieNode[T]()
            self.trie[domain_key] = domain_trie

        path_key = PurePosixPath(key.path.lstrip("/")).parts
        domain_trie[path_key] = value

    def __getitem__(self, key: URI) -> T:
        domain_split = key.netloc.split(".")
        domain_key = tuple(reversed(domain_split))
        domain_trie = self.trie.get(domain_key)
        if domain_trie is None:
            raise KeyError(key)
        path_key = PurePosixPath(key.path.lstrip("/")).parts
        return domain_trie[path_key]

    def __delitem__(self, key: URI) -> None:
        domain_split = key.netloc.split(".")
        domain_key = tuple(reversed(domain_split))
        domain_trie = self.trie.get(domain_key)
        if domain_trie is None:
            return
        path_key = PurePosixPath(key.path.lstrip("/")).parts
        del domain_trie[path_key]
        if not domain_trie.branches:
            del self.trie[domain_key]
