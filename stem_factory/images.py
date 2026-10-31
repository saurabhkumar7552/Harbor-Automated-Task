"""Small syntactic guard for explicit task-image versions (not registry verification)."""
import re


def versioned_image(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_./:@-]+', value):
        return False
    if '@' in value:
        return bool(re.fullmatch(r'[^@]+@sha256:[a-f0-9]{64}', value))
    tail = value.rsplit('/', 1)[-1]
    if ':' not in tail:
        return False  # A registry port is not an image tag.
    name, tag = tail.rsplit(':', 1)
    return bool(name and tag.casefold() != 'latest' and
                re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag))
