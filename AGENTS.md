# Gossip

## Testing conventions

Test classes are grouped by the behavior/category they cover, not by the
function they call. Both the class and each test method get a docstring:

- **Class docstring**: one or two sentences naming the category of test and
  what it verifies as a whole. Describe the *behavior under test*, not the
  implementation - implementation detail belongs in the source method's own
  docstring, not here.
- **Test method docstring**: one or two sentences in plain English stating
  exactly what that test verifies. It should be specific enough that a
  reader can tell, without reading the test body, whether the assertions
  actually match - if the test's behavior drifts from its docstring, that
  mismatch should be obvious at a glance.

Example, from `tests/internet/test_mime.py`:

```python
class TestMediaTypeCovers:
    """Whether one `MediaType` matches every representation another one
    matches - across exact matches, wildcards, and types that don't relate
    at all."""

    def test_wildcard_subtype_covers_concrete_subtype(self):
        """A wildcard subtype covers a concrete one, but not the other way
        around."""
        assert MediaType.text("*").covers(MediaType.text("html"))
        assert not MediaType.text("html").covers(MediaType.text("*"))
```

### Synthetic test data

When a test needs an instance of some class under test filled with
plausible data, generate it with a subclass named `Dummy<Whatever>` that
calls the superclass constructor with reasonable defaults - not a bare
`make_whatever()` function or inline construction repeated across tests.
It should be obvious what the class is for and trivial to get an instance
of it. If the class has a few genuinely distinct shapes worth covering
(e.g. DNS records vary a lot by RDATA per record type), add `@classmethod`
factories for those instead of trying to cram them into one constructor
signature.

The `Dummy` prefix (not `Test`) is deliberate: pytest collects any
`Test*`-named class visible in a test module's namespace, including ones
merely imported into it, so a factory named e.g. `TestRecord` gets treated
as a test class the moment it's imported into `test_model.py`, misparsed or
emitting a `PytestCollectionWarning`. `Dummy` sidesteps the problem outright
- no `__test__ = False` workaround needed. (`Mock` was considered and
rejected: these are real subclasses producing genuine instances, not test
doubles that fake or intercept behavior, so it would misdescribe them.)

These classes still go in their own module, named after the source module
they provide data for (e.g. `tests/dns/model.py` for factories used against
`gossip.dns.model`), rather than inline in the `test_*.py` file that uses
them - keeps the test file focused on behavior, not setup.

Example, from `tests/dns/model.py`:

```python
class DummyRecord(Record):
    """A record for a fixed example domain, A/IN, 300s TTL, and empty RDATA
    unless overridden."""

    def __init__(self, domain="example.com", rtype=RecordType.A, rclass=RecordClass.IN, ttl=timedelta(seconds=300), rdata=b""):
        super().__init__(DNSKey._encode_domain(domain), rtype, rclass, ttl, rdata)
```

If a factory on one of these classes turns out to be useful beyond just
building test data - not something test-specific, but a shape the
production class itself should know how to build - promote it to the real
class instead of leaving it stuck on the `Dummy<Whatever>` wrapper. That's
why `Record.address()`/`.domain_target()`/`.mx()` live in
`gossip/dns/model.py` (alongside `.delete()`/`.insert()`/`.tsig()`) rather
than on `DummyRecord`: they're generally-useful ways to build a `Record`,
not test-only conveniences.

### Serialized data as external files

A test that needs a chunk of serialized data as a fixture (an XML document,
a wire capture, etc.) belongs in its own file under a `data/` directory
next to the tests that use it (e.g. `tests/upnp/data/`), not as a large
string literal inline in the test module. Load it with `pathlib` relative
to `__file__`.

### Avoid magic bytes in test data

Prefer generating test input through the real encoding functions (e.g.
`DNSKey._encode_domain()`, `struct.pack()`, `ip.packed`) over hand-written
byte literals - a magic `b"\x00\x0a..."` blob tells a reader nothing about
what it represents. Two exceptions:

- A byte value that's a fixed, named part of the wire protocol itself
  (e.g. the root domain's single `b"\x00"` terminator octet, or a
  compression pointer's `0xC0` marker bit), where the test is explicitly
  about that constant and there's nothing to generate.
- Deliberately malformed input for an error-path test, where the whole
  point is bytes that couldn't have come from the real encoder - though
  even then, prefer deriving it from a well-formed encoding where that's a
  one-liner (e.g. `IPv4Address("1.2.3.4").packed[:3]` for a truncated A
  record, rather than an opaque literal).

If generating the bytes would take more than a line or two, a raw literal
is fine - don't build a small parser just to avoid one.
