"""Contact confirmation (005 S1.2 Confirm; J-03; ADR-16, D-24): an explicit, expiring, single-use proof
that the applicant controls the address.

The link carries the challenge's public id signed with the dedicated verification key (applications/links.py).
The signature only makes the link unguessable; the raw public id never authorizes anything. Whether the
challenge may still be used is decided here, by the database alone, every time: the worker's pre-send
check is not a guarantee (a message may be in flight after a repeat or a confirmation, and D-20 may
redeliver the identical link).

`preview` (GET) reads and changes nothing. `confirm` (POST) is one transaction. It locks the application,
then the challenge (the order intake and the worker use), and checks that the challenge is unused, not
superseded and unexpired by the database clock, and that the named version belongs to this application.
It then records, all once:
- contact control (`contact_verified_at`, stage `contact_verified`) and the challenge as used;
- an adoption of **only the named version**; every other version stays unverified;
- a `contact_verified` event, plus a `needs_staff_attention` event if any newer unverified version exists;
- the `start_evidence_collection` action, `held`, with the adopted version as its explicit input. No
  handler exists for it in S1, so nothing runs it.
Confirmation proves control of the address, not authorship of other versions.

A second confirmation of the same link finds the challenge used and changes nothing ("already confirmed").
Refusals carry a reason code only: never the token, the link, an address or an answer.
"""

from dataclasses import dataclass
from uuid import UUID

from django.core.signing import BadSignature
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Now

from workflow.models import PendingAction

from .links import signer
from .models import OPEN_STAGES, Application, ApplicationEvent, ContactChallenge, Stage, SubmissionVersion, VersionAdoption

START_EVIDENCE_COLLECTION = "start_evidence_collection"


def start_evidence_collection_key(application_public_ref) -> str:
    """005 S1.4: the next-stage action is keyed by application, so it can exist at most once."""
    return f"{START_EVIDENCE_COLLECTION}:{application_public_ref}"


class Refused(Exception):
    """The link or the request cannot confirm anything. `kind` selects the page; `reason` is a code."""

    INVALID = "invalid"  # bad signature or no such challenge
    NO_LONGER_VALID = "no_longer_valid"  # expired, superseded or the application closed
    ALREADY = "already"  # the challenge was used: contact is already confirmed
    BAD_VERSION = "bad_version"  # the POST names no version of this application

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


@dataclass(frozen=True)
class Preview:
    version_public_id: UUID
    version_number: int
    fields: dict


@dataclass(frozen=True)
class Confirmed:
    version_number: int
    staff_item: bool


def _after_verification_write() -> None:
    """Test seam (TEST-S1-05): called after contact control is recorded, before the adoption. No-op."""


def challenge_id(token: str) -> UUID:
    try:
        return UUID(signer().unsign(token))
    except (BadSignature, ValueError):
        raise Refused(Refused.INVALID, "bad signature") from None


def _usable(challenge_uuid: UUID, *, lock: bool):
    """The application and challenge if the challenge may confirm now; otherwise Refused."""
    application_id = ContactChallenge.objects.filter(public_id=challenge_uuid).values_list("application_id", flat=True).first()
    if application_id is None:
        raise Refused(Refused.INVALID, "unknown challenge")
    applications, challenges = Application.objects, ContactChallenge.objects
    if lock:  # application, then challenge
        applications = applications.select_for_update(of=("self",))
        challenges = challenges.select_for_update(of=("self",))
    application = applications.get(pk=application_id)
    challenge = challenges.annotate(unexpired=Q(expires_at__gt=Now())).get(public_id=challenge_uuid)
    if challenge.used_at is not None or application.contact_verified_at is not None:
        raise Refused(Refused.ALREADY, "already confirmed")
    if challenge.superseded_at is not None:
        raise Refused(Refused.NO_LONGER_VALID, "challenge superseded")
    if not challenge.unexpired:
        raise Refused(Refused.NO_LONGER_VALID, "challenge expired")
    if application.stage not in OPEN_STAGES:
        raise Refused(Refused.NO_LONGER_VALID, "application closed")
    return application, challenge


def preview(challenge_uuid: UUID) -> Preview:
    """The current (latest) submission version's answers, for the confirm page. Writes nothing."""
    with transaction.atomic():
        application, _ = _usable(challenge_uuid, lock=False)
        version = application.versions.order_by("-version_number").first()
    return Preview(version.public_id, version.version_number, version.submitted_fields)


def confirm(challenge_uuid: UUID, version_public_id: UUID) -> Confirmed:
    with transaction.atomic():
        application, challenge = _usable(challenge_uuid, lock=True)
        version = SubmissionVersion.objects.filter(public_id=version_public_id, application=application).first()
        if version is None:
            raise Refused(Refused.BAD_VERSION, "version does not belong to the application")
        ContactChallenge.objects.filter(pk=challenge.pk).update(used_at=Now())
        Application.objects.filter(pk=application.pk).update(
            contact_verified_at=Now(), stage=Stage.CONTACT_VERIFIED, updated_at=Now()
        )
        _after_verification_write()
        VersionAdoption.objects.create(application=application, submission_version=version, via_challenge=challenge)
        number = version.version_number
        event = dict(application=application, actor_type=ApplicationEvent.ActorType.APPLICANT)
        ApplicationEvent.objects.create(kind="contact_verified", data={"version_number": number}, **event)
        # Newer versions cannot appear meanwhile: intake needs the application lock held here.
        newer = list(application.versions.filter(version_number__gt=number).order_by("version_number")
                     .values_list("version_number", flat=True))
        if newer:
            ApplicationEvent.objects.create(kind="needs_staff_attention", data={
                "reason": "newer_unverified_version", "adopted_version_number": number, "unverified_version_numbers": newer,
            }, **event)
        PendingAction.objects.create(
            kind=START_EVIDENCE_COLLECTION,
            subject_type="application",
            subject_id=application.public_ref,
            input_ref=str(version.public_id),
            idempotency_key=start_evidence_collection_key(application.public_ref),
            status=PendingAction.Status.HELD,
        )
    return Confirmed(number, bool(newer))
