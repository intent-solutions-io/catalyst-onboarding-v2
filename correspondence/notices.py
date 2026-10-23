"""The template source behind `applications.notices` (9kg.52): the data notice and the invitation mail as message
templates, read and rendered here and reached from `applications` only through the fixed path in
`CATALYST_NOTICE_SOURCE` (003 ADR-01: `applications` never imports this app; `correspondence` may import it).

Only an approved version renders (016 A1; correspondence.rendering, the template engine-free renderer). A draft is
handed back as its fields, never rendered here: `applications.notices` decides, by environment, whether a marked
draft may be shown at all.
"""

from applications.notices import Draft, Rendered

from .models import MessageTemplateVersion
from .rendering import render


def _newest(key: str, status: str):
    return (MessageTemplateVersion.objects.select_related("template")
            .filter(template__key=key, status=status).order_by("-version").first())


def approved(key: str, values: dict) -> Rendered | None:
    """The newest approved version rendered with `values`, or None when none is approved."""
    version = _newest(key, MessageTemplateVersion.Status.APPROVED)
    if version is None:
        return None
    subject, text = render(version, values)
    return Rendered(version.version, version.content_sha256, subject, text)


def draft(key: str) -> Draft | None:
    """The newest draft's fields (unrendered), or None when there is none."""
    version = _newest(key, MessageTemplateVersion.Status.DRAFT)
    if version is None:
        return None
    return Draft(version.version, version.content_sha256, version.subject, version.body_text, tuple(version.variables))


def status(key: str) -> dict:
    """For the health report: the state of the wording with its version and digest, never the wording."""
    for state in (MessageTemplateVersion.Status.APPROVED, MessageTemplateVersion.Status.DRAFT):
        version = _newest(key, state)
        if version is not None:
            return {"status": state.value, "version": version.version, "sha256": version.content_sha256}
    return {"status": "missing", "version": None, "sha256": ""}
