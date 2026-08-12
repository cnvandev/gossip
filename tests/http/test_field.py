from gossip.http.field import parse_field_values, parse_parameters


class TestParseParameters:
    """Parsing the `;`-separated `key=value` parts of a field value (as in
    `text/html;charset=utf-8;q=0.9`) into a dict."""

    def test_single_parameter(self):
        """A single `key=value` part parses into a one-entry dict."""
        assert parse_parameters(["q=0.9"]) == {"q": "0.9"}

    def test_multiple_parameters(self):
        """Each `;`-separated part becomes its own entry."""
        assert parse_parameters(["charset=utf-8", "q=0.9"]) == {"charset": "utf-8", "q": "0.9"}

    def test_strips_surrounding_whitespace(self):
        """Whitespace around a part (as left behind by splitting on `;`)
        doesn't end up in the key or value."""
        assert parse_parameters([" charset=utf-8 "]) == {"charset": "utf-8"}

    def test_part_without_equals_sign_gets_empty_value(self):
        """A bare part with no `=` (e.g. a flag-like `charset` instead of
        `charset=utf-8`) is treated as having an empty value, rather than
        raising."""
        assert parse_parameters(["charset"]) == {"charset": ""}

    def test_no_parameters_yields_empty_dict(self):
        """An empty list of parts parses into an empty dict."""
        assert parse_parameters([]) == {}


class TestParseFieldValues:
    """Parsing a comma-separated field value (as in `Accept` or
    `Accept-Language`) into one `(value, params)` pair per element."""

    def test_single_value_with_no_parameters(self):
        """A single element with no `;`-separated parameters yields an
        empty params dict."""
        assert list(parse_field_values("text/html")) == [("text/html", {})]

    def test_single_value_with_parameters(self):
        """A single element's `;`-separated parameters are parsed via
        `parse_parameters()`."""
        assert list(parse_field_values("text/html;q=0.9")) == [("text/html", {"q": "0.9"})]

    def test_multiple_comma_separated_values(self):
        """Each comma-separated element becomes its own `(value, params)`
        pair, in the order given."""
        parsed = list(parse_field_values("text/html;q=0.9, application/json;q=0.5"))
        assert parsed == [("text/html", {"q": "0.9"}), ("application/json", {"q": "0.5"})]

    def test_strips_surrounding_whitespace_from_value(self):
        """Whitespace around an element (as left behind by splitting on
        `,`) doesn't end up in the value."""
        assert list(parse_field_values("text/html, application/json")) == [("text/html", {}), ("application/json", {})]
