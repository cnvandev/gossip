import gzip
import zlib
from asyncio import StreamReader
from asyncio import run as run_async

import pytest

from gossip.http.transfer import choose_encoding
from gossip.internet.serialization.encoded import ChunkEncodedReader
from gossip.network.serializer import BufferedReader


class TestChooseEncoding:
    """`choose_encoding()` wraps a body according to a list of
    transfer-coding names, per RFC 9112 §6.1 - codings are unwrapped in
    reverse of the order they were applied, and `chunked`, if present,
    must be the last one listed."""

    def test_no_codings_returns_body_unchanged(self):
        body = BufferedReader.for_bytes(b"hi")
        assert choose_encoding([], body) is body

    def test_none_body_returns_none(self):
        assert choose_encoding(["chunked"], None) is None

    def test_identity_is_a_no_op(self):
        body = BufferedReader.for_bytes(b"hi")
        assert choose_encoding(["identity"], body) is body

    def test_chunked_wraps_in_chunk_encoded_reader(self):
        async def build() -> StreamReader | None:
            body = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            return choose_encoding(["chunked"], body)

        assert isinstance(run_async(build()), ChunkEncodedReader)

    def test_chunked_body_decodes_correctly(self):
        async def read_it() -> bytes:
            body = BufferedReader.for_bytes(b"5\r\nhello\r\n0\r\n\r\n")
            decoded = choose_encoding(["chunked"], body)
            assert decoded is not None
            return await decoded.read()

        assert run_async(read_it()) == b"hello"

    def test_gzip_then_chunked_decodes_both_layers(self):
        """`gzip, chunked` means gzip was applied first and chunked
        second, so decoding un-chunks first, then un-gzips."""

        async def read_it() -> bytes:
            compressed = gzip.compress(b"hello world")
            wire = f"{len(compressed):x}".encode() + b"\r\n" + compressed + b"\r\n0\r\n\r\n"
            body = BufferedReader.for_bytes(wire)
            decoded = choose_encoding(["gzip", "chunked"], body)
            assert decoded is not None
            return await decoded.read()

        assert run_async(read_it()) == b"hello world"

    def test_deflate_is_decoded(self):
        async def read_it() -> bytes:
            compressed = zlib.compress(b"hello world")
            decoded = choose_encoding(["deflate"], BufferedReader.for_bytes(compressed))
            assert decoded is not None
            return await decoded.read()

        assert run_async(read_it()) == b"hello world"

    def test_chunked_not_last_is_rejected(self):
        with pytest.raises(ValueError):
            choose_encoding(["chunked", "gzip"], BufferedReader.for_bytes(b""))

    def test_unsupported_coding_is_rejected(self):
        with pytest.raises(ValueError):
            choose_encoding(["compress"], BufferedReader.for_bytes(b""))
