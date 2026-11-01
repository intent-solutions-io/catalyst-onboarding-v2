"""Template rendering and the canonical content digest (016 3.1, 3.2; A1).

Only an approved version renders. Bodies use `$name` placeholders substituted from the version's
allow-list only; the Django template engine is never used for message text, and subjects are static. Any
placeholder outside the allow-list, or any missing or extra value, fails closed: nothing is rendered.

The canonical digest (016 3.2) is SHA-256 over the decoded subject, a line feed, and the decoded text
body with line endings normalized to line feeds. A5 compares provider evidence with the same digest.

The HTML alternative (bgl.11): a version may carry `body_html`, rendered by `render_html` from the same values under
the same allow-list, every value HTML-escaped. A link variable (models.LINK_VARIABLES) may stand only as the whole
value of an `href="..."` the author wrote, and its value must be an http(s) URL; any other variable may stand only in
text content (never inside a tag, a comment, a `<style>` block, and no version may hold `<script`). The version's
digest (`version_digest`) covers the HTML when there is one and is the canonical digest otherwise, so every existing
text-only version keeps its digest. A sent message's digest stays the canonical digest of its subject and text: that is
what A5 recomputes from the provider's copy (its text/plain part).
"""

import hashlib
import html
import re
from string import Template

_HREF_OPEN = re.compile(r"""\shref\s*=\s*"$""", re.IGNORECASE)
_SAFE_LINK = re.compile(r"https?://[^\s\"'<>`]+")


class TemplateRefused(Exception):
    """A version that is not approved, or values that do not match its allow-list. The message is a reason
    code; it never carries the values."""


def canonical_digest(subject: str, body: str) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(f"{subject}\n{normalized}".encode()).hexdigest()


def version_digest(subject: str, body: str, body_html: str = "") -> str:
    """A template version's content digest: the canonical digest for a text-only version; with an HTML part, SHA-256
    over the canonical form, a NUL separator line and the HTML with line endings normalized."""
    if not body_html:
        return canonical_digest(subject, body)
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    page = body_html.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(f"{subject}\n{text}\n\x00text/html\n{page}".encode()).hexdigest()


def placeholders(body_text: str) -> set[str]:
    return set(Template(body_text).get_identifiers())


# The greeting pair (parity integration of bgl.11): every applicant-facing sender offers the applicant's display name,
# and with it the first name, the way the first generation greets; a version declares the one its greeting uses.
GREETING = ("display_name", "first_name")


def first_name(display_name: str) -> str:
    """The first word of the applicant's name as submitted (the display name), trimmed; the display name itself when
    that word is empty (a blank name)."""
    words = str(display_name or "").split()
    return words[0] if words else str(display_name or "")


def fit_greeting(variables, values: dict) -> dict:
    """`values` with the greeting pair fitted to a version's allow-list: when the sender offers `display_name`, the
    first name is derived from it (unless the sender gave one), and each of the two is kept only if the version
    declares it. Every other value is left exactly as given, so the allow-list check still applies to it."""
    if "display_name" not in values:
        return dict(values)
    offered = {"display_name": values["display_name"],
               "first_name": values.get("first_name") or first_name(values["display_name"])}
    declared = set(variables)
    fitted = {name: value for name, value in values.items() if name not in GREETING}
    fitted.update({name: offered[name] for name in GREETING if name in declared})
    return fitted


def _link_variables() -> list[str]:
    from .models import LINK_VARIABLES  # imported late: this module is a leaf other modules load before the app registry

    return LINK_VARIABLES


def html_placement_problem(body_html: str) -> str:
    """Why a placeholder stands where it may not in an HTML part, or "" (see the module docstring)."""
    links = _link_variables()
    lowered = body_html.lower()
    if "<script" in lowered:
        return "html_script_refused"
    for match in Template.pattern.finditer(body_html):
        name = match.group("named") or match.group("braced")
        if not name:
            continue
        start, end = match.start(), match.end()
        tag_open = body_html.rfind("<", 0, start)
        in_tag = tag_open > body_html.rfind(">", 0, start)
        in_comment = lowered.rfind("<!--", 0, start) > lowered.rfind("-->", 0, start)
        in_style = lowered.rfind("<style", 0, start) > lowered.rfind("</style", 0, start)
        if in_comment or in_style:
            return "html_placeholder_in_comment_or_style"
        if name in links:
            if not (in_tag and _HREF_OPEN.search(body_html[tag_open:start]) and body_html[end:end + 1] == '"'):
                return "html_link_outside_href"
        elif in_tag:
            return "html_placeholder_inside_tag"
    return ""


def check_version(version) -> None:
    """The structural rules an approvable version must meet."""
    allowed = set(version.variables)
    if not placeholders(version.body_text) <= allowed:
        raise TemplateRefused("placeholder_outside_allow_list")
    if not Template(version.body_text).is_valid():
        raise TemplateRefused("invalid_placeholder")
    if version.secret_bearing != version.template.secret_bearing:
        raise TemplateRefused("secret_bearing_mismatch")
    page = getattr(version, "body_html", "") or ""
    if page:
        if not placeholders(page) <= allowed:
            raise TemplateRefused("placeholder_outside_allow_list")
        if not Template(page).is_valid():
            raise TemplateRefused("invalid_placeholder")
        problem = html_placement_problem(page)
        if problem:
            raise TemplateRefused(problem)
    if version_digest(version.subject, version.body_text, page) != version.content_sha256:
        raise TemplateRefused("content_digest_mismatch")


def render(version, values: dict) -> tuple[str, str]:
    values = fit_greeting(version.variables, values)
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


def _substitute_html(page: str, values: dict) -> str:
    escaped, links = {}, _link_variables()
    for name, value in values.items():
        value = str(value)
        if name in links and not _SAFE_LINK.fullmatch(value):
            raise TemplateRefused("link_value_refused")
        escaped[name] = html.escape(value, quote=True)
    try:
        return Template(page).substitute(escaped)
    except (KeyError, ValueError):
        raise TemplateRefused("substitution_failed") from None


def render_html(version, values: dict) -> str:
    """The HTML alternative rendered with `values` (each HTML-escaped), or "" when the version has none. The same
    refusals as `render`, plus a link value that is not an http(s) URL."""
    page = getattr(version, "body_html", "") or ""
    if not page:
        return ""
    values = fit_greeting(version.variables, values)
    if version.status != "approved":
        raise TemplateRefused("template_version_not_approved")
    check_version(version)
    if set(values) != set(version.variables):
        raise TemplateRefused("values_do_not_match_allow_list")
    return _substitute_html(page, values)


HTML_VALUES = "html_values"  # the key of a frozen message's reproducible inputs that carries its HTML values


def html_inputs(version, values: dict) -> dict:
    """The reproducible inputs to freeze with a message (bgl.11): its values when the version has an HTML part, so the
    sender can rebuild the same HTML; {} otherwise. Renders once, so a refusal happens at freezing, not at sending."""
    if not (getattr(version, "body_html", "") or ""):
        return {}
    values = fit_greeting(version.variables, values)  # frozen as fitted, so the sender rebuilds the same text
    render_html(version, values)
    return {HTML_VALUES: {name: str(value) for name, value in values.items()}}


def frozen_html(message) -> str:
    """The HTML alternative of a frozen message, or "" when it was frozen without one (a text-only version, or a draft
    sent with its marker). The values must reproduce the frozen text exactly, so the HTML says what the approved text
    says; anything else is a refusal."""
    version = message.template_version
    values = (message.reproducible_inputs or {}).get(HTML_VALUES)
    if version is None or not (version.body_html or "") or values is None:
        return ""
    if not isinstance(values, dict) or set(values) != set(version.variables):
        raise TemplateRefused("html_inputs_invalid")
    check_version(version)
    try:
        text = Template(version.body_text).substitute({name: str(value) for name, value in values.items()})
    except (KeyError, ValueError):
        raise TemplateRefused("substitution_failed") from None
    if text != message.frozen_body:
        raise TemplateRefused("html_inputs_mismatch")
    return _substitute_html(version.body_html, values)
