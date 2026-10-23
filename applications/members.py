"""Members whose first-generation agreement is on file (9kg.52; 030 Q4, D-51): "referenced, not re-signed".

The owner records the fact by hand from the private roster through the owner-run `catalyst_member_on_file`: the
agreement version as a plain label and that completion was verified. No legacy identifier and no document copy enter
v2, so the command refuses a value that looks like a reference (a link, a path, an identifier) rather than a label,
and a member without a verified completion gets no row at all (a new participant signs the current versions on v2's
own templates). The row is the audit record (migration 0008 fixes it; a correction supersedes the live row), and the
staff dossier shows the state per applicant. The decision form's refusal of a v2 decline for a member on file is
built with the decision policy identifier after PR #87 (030 Q8, Legacy seat); `on_file` is what it will read.
"""

from django.db import transaction
from django.db.models.functions import Now

from .identity import email_key
from .models import MemberAgreementOnFile

LABEL_MAX = MemberAgreementOnFile._meta.get_field("agreement_version").max_length
# A version label is a short plain phrase. Anything with a scheme, a path separator, a long digit run or a line
# break reads as an identifier, a link or a pasted record, none of which may enter v2 (030 Q4).
REFERENCE_MARKS = ("://", "/", "\\", "\n", "\r", "\t")


class NotALabel(ValueError):
    """The agreement version is not a plain label. The message is a reason code."""


def check_label(value: str) -> str:
    label = " ".join(value.split())
    if not label:
        raise NotALabel("agreement_version_empty")
    if len(label) > LABEL_MAX:
        raise NotALabel("agreement_version_too_long")
    if any(mark in value for mark in REFERENCE_MARKS):
        raise NotALabel("agreement_version_looks_like_a_reference")
    if any(len(run) >= 8 for run in "".join(c if c.isdigit() else " " for c in label).split()):
        raise NotALabel("agreement_version_looks_like_an_identifier")
    return label


def record(email: str, agreement_version: str, recorded_by: str, note: str = "") -> tuple[MemberAgreementOnFile, int]:
    """Owner path only (the application role may not insert). Supersedes the live row for the address, if any, and
    records the new one with completion verified. Returns it and how many were superseded (0 or 1)."""
    key = email_key(email)
    label = check_label(agreement_version)
    with transaction.atomic():
        superseded = MemberAgreementOnFile.objects.filter(email_key=key, superseded_at__isnull=True).update(superseded_at=Now())
        row = MemberAgreementOnFile.objects.create(email_key=key, agreement_version=label, completion_verified=True,
                                                   recorded_by=recorded_by, note=note)
        row.refresh_from_db()  # the database clock's value
    return row, superseded


def on_file(application) -> MemberAgreementOnFile | None:
    return MemberAgreementOnFile.objects.filter(email_key=application.email_key, superseded_at__isnull=True).first()


def describe(application) -> str:
    """One line for the staff dossier: a visible state, never a document and never an identifier."""
    row = on_file(application)
    if row is None:
        return "new participant: no first-generation agreement on file; signs the current versions"
    return (f"agreement on file, first-generation: {row.agreement_version}; completion verified; "
            f"recorded by {row.recorded_by} at {row.recorded_at:%Y-%m-%d %H:%M:%S} UTC")
