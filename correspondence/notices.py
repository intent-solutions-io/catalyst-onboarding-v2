"""The template source behind `applications.notices` (9kg.52): the data notice and the invitation mail as message
templates, read and rendered here and reached from `applications` only through the fixed path in
`CATALYST_NOTICE_SOURCE` (003 ADR-01: `applications` never imports this app; `correspondence` may import it).

Only an approved version renders (016 A1; correspondence.rendering, the template engine-free renderer), and only
while it is the newest approved-or-retired version: when the newest of those is retired, the wording was withdrawn
and nothing older is served in its place (`<key>_retired`). The version's `synthetic` flag travels with it, so a
placeholder the owner approved for a drill is still refused where real people read it (`applications.notices`). A
draft is handed back as its fields, never rendered here. Any rendering failure is a refusal with a reason code,
never an error page.
"""

from applications.notices import Draft, Rendered, Unavailable

from .models import MessageTemplateVersion
from .rendering import TemplateRefused, render

Status = MessageTemplateVersion.Status


def _versions(key: str):
    return MessageTemplateVersion.objects.select_related("template").filter(template__key=key)


def _current(key: str):
    """The newest approved-or-retired version, or None when the template was never approved."""
    return _versions(key).filter(status__in=(Status.APPROVED, Status.RETIRED)).order_by("-version").first()


def approved(key: str, values: dict) -> Rendered | None:
    """The newest approved version rendered with `values`, or None when none was ever approved."""
    version = _current(key)
    if version is None:
        return None
    if version.status == Status.RETIRED:
        raise Unavailable(f"{key}_retired")
    try:
        subject, text = render(version, values)
    except TemplateRefused as refused:
        raise Unavailable(f"{key}_{refused}") from None
    return Rendered(version.version, version.content_sha256, subject, text, synthetic=version.synthetic,
                    subject_reference=version.subject_reference)


def draft(key: str) -> Draft | None:
    """The newest draft's fields (unrendered), or None when there is none."""
    version = _versions(key).filter(status=Status.DRAFT).order_by("-version").first()
    if version is None:
        return None
    return Draft(version.version, version.content_sha256, version.subject, version.body_text, tuple(version.variables),
                 subject_reference=version.subject_reference)


def status(key: str) -> dict:
    """For the health report: the state of the wording with its version, digest and synthetic flag, never the wording."""
    version = _current(key) or _versions(key).filter(status=Status.DRAFT).order_by("-version").first()
    if version is None:
        return {"status": "missing", "version": None, "sha256": "", "synthetic": False}
    return {"status": str(version.status), "version": version.version, "sha256": version.content_sha256,
            "synthetic": version.synthetic}
