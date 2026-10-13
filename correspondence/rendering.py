"""Template rendering and the canonical content digest (016 3.1, 3.2; A1).

Only an approved version renders. Bodies use `$name` placeholders substituted from the version's
allow-list only; the Django template engine is never used for message text, and subjects are static. Any
placeholder outside the allow-list, or any missing or extra value, fails closed: nothing is rendered.

The canonical digest (016 3.2) is SHA-256 over the decoded subject, a line feed, and the decoded text
body with line endings normalized to line feeds. A5 compares provider evidence with the same digest.
"""

import hashlib
from string import Template


class TemplateRefused(Exception):
    """A version that is not approved, or values that do not match its allow-list. The message is a reason
    code; it never carries the values."""


def canonical_digest(subject: str, body: str) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(f"{subject}\n{normalized}".encode()).hexdigest()


def placeholders(body_text: str) -> set[str]:
    return set(Template(body_text).get_identifiers())


def check_version(version) -> None:
    """The structural rules an approvable version must meet."""
    allowed = set(version.variables)
    if not placeholders(version.body_text) <= allowed:
        raise TemplateRefused("placeholder_outside_allow_list")
    if not Template(version.body_text).is_valid():
        raise TemplateRefused("invalid_placeholder")
    if version.secret_bearing != version.template.secret_bearing:
        raise TemplateRefused("secret_bearing_mismatch")
    if canonical_digest(version.subject, version.body_text) != version.content_sha256:
        raise TemplateRefused("content_digest_mismatch")


def render(version, values: dict) -> tuple[str, str]:
    if version.status != "approved":
        raise TemplateRefused("template_version_not_approved")
    check_version(version)
    if set(values) != set(version.variables):
        raise TemplateRefused("values_do_not_match_allow_list")
    try:
        body = Template(version.body_text).substitute(values)  # values are not re-expanded
    except (KeyError, ValueError):
        raise TemplateRefused("substitution_failed") from None
    return version.subject, body
