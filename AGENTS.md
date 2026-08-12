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
