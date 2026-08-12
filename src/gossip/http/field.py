from collections.abc import Iterable, Iterator

from gossip.utils.multidict import multidict


def parse_parameters(parts: Iterable[str]) -> multidict:
    """Parse the `;`-separated parameters of a field value (as in
    `text/html;charset=utf-8;q=0.9`) into a multidict.

    Per RFC 9110 §5.6.6 ("Parameters"), `parameters = *( OWS ";" OWS
    [ parameter ] )` and `parameter = parameter-name "=" parameter-value` -
    this is the generic parameter syntax shared by many fields (`Accept`,
    `Accept-Language`, `Content-Type`, ...), not something specific to any
    one of them. A part with no `=` (e.g. a bare `charset` instead of
    `charset=utf-8`) is treated as having an empty value, rather than
    raising.
    """
    return multidict((key, value) for key, _, value in (part.strip().partition("=") for part in parts))


def parse_field_values(field: str) -> Iterator[tuple[str, multidict]]:
    """Parse a comma-separated field value like
    `text/html;q=0.9, application/json;q=0.5` into `(value, params)` pairs,
    one per comma-separated element, with each element's parameters already
    parsed via `parse_parameters()`.

    Per RFC 9110 §5.6.1 ("Lists (#rule ABNF Extension)"), `1#element =>
    element *( OWS "," OWS element )` - the comma-separated list convention
    used throughout HTTP field values, not something specific to any one
    field.
    """
    for entry in field.split(","):
        value, *parts = entry.strip().split(";")
        yield value, parse_parameters(parts)
