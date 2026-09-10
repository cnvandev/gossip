from asyncio.streams import StreamReader
from collections.abc import Iterable

from gossip.internet.serialization.encoded import ChunkEncodedReader, DeflateEncodedReader, GzipEncodedReader


def choose_encoding(codings: Iterable[str], body: StreamReader | None) -> StreamReader | None:
    """Wraps `body` according to `codings`, a list of transfer-coding
    names (already parsed and lower-cased by the caller, e.g. from a
    `Transfer-Encoding` header) in the order they were applied when the
    message was written - see RFC 9112 §6.1.

    Decoding walks `codings` in reverse, wrapping `body` once per coding.
    `chunked`, if present, must be the last coding listed - it's what
    determines where the message body actually ends, so anything else
    applied after it would make the framing ambiguous.

    Raises `ValueError` if `chunked` isn't last, or if a coding this
    doesn't know how to reverse is named, rather than guessing at the
    framing or passing bytes through undecoded - per the security
    guidance in RFC 9112 §6.1, ambiguous message framing is exactly what
    request-smuggling attacks rely on.
    """
    if body is None:
        return body

    codings = list(codings)
    if "chunked" in codings and codings[-1] != "chunked":
        raise ValueError(f"`chunked` must be the last transfer-coding, got: {codings}")

    for coding in reversed(codings):
        if coding == "chunked":
            body = ChunkEncodedReader(body)
        elif coding in ("gzip", "x-gzip"):
            body = GzipEncodedReader(body)
        elif coding == "deflate":
            body = DeflateEncodedReader(body)
        elif coding == "identity":
            continue
        else:
            raise ValueError(f"Unsupported transfer-coding: {coding!r}")

    return body
