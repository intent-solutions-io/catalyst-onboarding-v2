"""Members whose first-generation agreements are on file (9kg.52; 030 Q4 and Q8, D-51): "referenced, not re-signed".

The owner records the fact by hand from the private roster through the owner-run `catalyst_member_on_file`: which
agreement types are covered, each with its version as an owner-typed plain label, and that completion was verified
off-system. No legacy identifier and no document copy enter v2: a label must match `LABEL` (letters, digits, spaces
and `.,()+-`, so no link, path, address or `@`) and may not hold a run of `RUN_MAX` or more characters without a
space (no pasted identifier). The recorder's name follows the same rule at `RECORDER_MAX` characters. A member without
a verified completion gets no row (a new participant), and an address v2 does not know (no invitation and no
application) is refused (`unknown_member`).

Recording is idempotent: the same coverage again returns the live row unchanged. Different coverage is a correction:
it needs `correct=True` and supersedes the live row, and the dossier then names what it was corrected from. The row is
the audit record (migration 0008 fixes it). Readers: `agreements.completion` (a covered type is "referenced": never
issued, never a verified instance), the dossier, the agreements screen and the decision form; the decision service
refuses a decline for a member on file (030 Q8).
"""

import re

from django.db import transaction
from django.db.models.functions import Now

from .identity import email_key
from .models import Application, Invitation, MemberAgreementOnFile

# The agreement types a first-generation record may cover, in order. Names only: `applications` never imports the
# agreements app (003 ADR-01); a test keeps this equal to the seeded agreement types.
COVERABLE = ("nda", "user_agreement")
LABEL = re.compile(r"^[A-Za-z0-9 .,()+-]{1,100}$")
RUN_MAX = 20
RECORDER_MAX = MemberAgreementOnFile._meta.get_field("recorded_by").max_length


class Refused(ValueError):
    """The record was refused. The message is a reason code."""


def _plain(value: str, limit: int, what: str) -> str:
    text = " ".join((value or "").split())
    if not text:
        raise Refused(f"{what}_empty")
    if len(text) > limit:
        raise Refused(f"{what}_too_long")
    if not LABEL.match(text) or "@" in value:
        raise Refused(f"{what}_not_a_plain_label")
    if any(len(run) >= RUN_MAX for run in text.split(" ")):
        raise Refused(f"{what}_looks_like_an_identifier")
    return text


def check_label(value: str) -> str:
    return _plain(value, 100, "label")


def check_recorder(value: str) -> str:
    return _plain(value, RECORDER_MAX, "recorded_by")


def check_covers(covers: dict) -> dict:
    cleaned = {key: check_label(label) for key, label in (covers or {}).items() if label is not None}
    if not cleaned:
        raise Refused("covers_nothing")
    if set(cleaned) - set(COVERABLE):
        raise Refused("unknown_agreement_type")
    return {key: cleaned[key] for key in COVERABLE if key in cleaned}


def known(key: str) -> bool:
    return Invitation.objects.filter(email_key=key).exists() or Application.objects.filter(email_key=key).exists()


def record(email: str, covers: dict, recorded_by: str, *, correct: bool = False) -> tuple[MemberAgreementOnFile, str]:
    """Owner path only (the application role may not insert). Returns the live row and what happened: "recorded",
    "unchanged" (the same coverage again) or "corrected" (a different coverage with `correct`, superseding)."""
    key = email_key(email)
    cleaned, recorder = check_covers(covers), check_recorder(recorded_by)
    with transaction.atomic():
        if not known(key):
            raise Refused("unknown_member")
        live = MemberAgreementOnFile.objects.select_for_update().filter(email_key=key, superseded_at__isnull=True).first()
        if live is not None and live.covers == cleaned:
            return live, "unchanged"
        if live is not None and not correct:
            raise Refused("different_record_needs_correct")
        if live is not None:
            MemberAgreementOnFile.objects.filter(pk=live.pk).update(superseded_at=Now())
        row = MemberAgreementOnFile.objects.create(email_key=key, covers=cleaned, completion_verified=True,
                                                   recorded_by=recorder)
        row.refresh_from_db()  # the database clock's value
    return row, "corrected" if live is not None else "recorded"


def on_file(application) -> MemberAgreementOnFile | None:
    return MemberAgreementOnFile.objects.filter(email_key=application.email_key, superseded_at__isnull=True).first()


def covers(application) -> dict:
    """{agreement type key: label} for the live record, or {} for a new participant."""
    row = on_file(application)
    return dict(row.covers) if row is not None else {}


def _labels(covers_: dict) -> str:
    return ", ".join(f"{key} {label}" for key, label in covers_.items())


def describe(application) -> str:
    """One line for the staff dossier: a visible state, never a document and never an identifier."""
    row = on_file(application)
    if row is None:
        return "new participant: no first-generation agreement on file; signs the current versions"
    text = (f"agreement on file, first-generation: {_labels(row.covers)}; completion verified by the owner off-system"
            f" (attested, not read from the provider); recorded by {row.recorded_by} at {row.recorded_at:%Y-%m-%d %H:%M:%S} UTC")
    previous = (MemberAgreementOnFile.objects.filter(email_key=row.email_key, superseded_at__isnull=False)
                .order_by("-superseded_at", "-id").first())
    if previous is not None:
        text += f"; corrected from {_labels(previous.covers)}"
    return text
