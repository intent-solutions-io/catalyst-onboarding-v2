"""034 row 8: historical owner-review triggers, never a legal finding or automatic decline.

The carried-forward policy was reviewed on 2026-10-06. These are conservative review
signals, not a statement of current legal prohibitions. A phone prefix does not establish
residence. Changes to this list require a reviewed policy change. Only adopted answers
control processing; a later unverified submission cannot change that decision.
"""

REASON = "sanctions_concern"
VERSION = "geographic-human-review.v1"
RESIDENCES = frozenset({"CU", "IR", "KP", "SY", "UA-43", "UA-40", "UA-14", "UA-09"})
PHONE_PREFIXES = (
    "53",
    "98",
    "850",
    "963",
    "7978",
    "7365",
    "7869",
    "7949",
    "7959",
    "38071",
    "38072",
    "38065",
    "38069",
)


def signals(fields):
    """Return reason categories only; never copy a phone number into audit metadata."""
    fields = fields or {}
    found = []
    if fields.get("residence_country") in RESIDENCES:
        found.append("residence_review")
    phone = fields.get("phone_e164", "")
    if isinstance(phone, str) and phone.startswith(
        tuple("+" + p for p in PHONE_PREFIXES)
    ):
        found.append("phone_prefix_review")
    return found


def evidence(application):
    # Admission probes without an applicant still check provider approval.
    if application is None:
        return {}
    adoption = application.adoptions.select_related("submission_version").first()
    if adoption is None:
        return {}
    version = adoption.submission_version
    matched = signals(version.submitted_fields)
    return (
        {"policy": VERSION, "version": str(version.public_id), "signals": matched}
        if matched
        else {}
    )


def ensure_hold(application):
    """Called with the application locked. A reviewed item stays resolved; the model gate remains."""
    from .models import ApplicationEvent
    from .services import open_staff_item

    value = evidence(application)
    if value:
        if not application.events.filter(
            kind="needs_staff_attention",
            data__reason=REASON,
            data__version=value["version"],
            data__policy=value["policy"],
        ).exists():
            attention = ApplicationEvent.objects.create(
                application=application,
                kind="needs_staff_attention",
                actor_type="system",
                data={"reason": REASON, **value},
            )
            open_staff_item(application, REASON, attention)
    return value
