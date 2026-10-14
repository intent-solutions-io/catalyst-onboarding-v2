"""What the staff dossier says about one application (005 S1.2 Staff; S1-T7). Derived only from existing
records, read-only, and never from or about a token: challenges are described by their state and times,
pending actions by kind and status (their inputs and idempotency keys name challenge ids, so they are not
shown).

Staff attention, one rule for the dossier, the list column and the list filter (`attention_q`):
- an open staff item (016 3.8, A-2; P2 task 2B.3). Every `needs_staff_attention` event also opens one, and
  migration correspondence 0008 opened one for each earlier event, so resolving the item clears the mark;
- an automation pause on the application;
- while contact is unverified and the application open: an active, unexpired challenge whose send is
  missing or ended in anything but queued, running or done (failed, uncertain, cancelled, held), so the
  applicant has no working link and nothing automatic will produce one;
- once contact is verified: no next-stage action.
Every other next step belongs to the applicant, the system, or nobody yet (blocked in this slice).
"""

from dataclasses import dataclass


from django.db.models import CharField, Exists, OuterRef, Q, Value
from django.db.models.functions import Cast, Concat, Now

from workflow.models import AutomationPause, PendingAction

from .confirmation import START_EVIDENCE_COLLECTION
from .models import TERMINAL_STAGES, Application, ApplicationEvent, ContactChallenge
from .services import SEND_VERIFICATION, send_verification_key

ATTENTION = "needs_staff_attention"
OK_SEND = (PendingAction.Status.QUEUED, PendingAction.Status.RUNNING, PendingAction.Status.DONE)
REASONS = {
    "repeat_after_verification": "a submission arrived after the address was verified; it was not adopted",
    "newer_unverified_version": "a newer submission exists than the one the applicant confirmed",
    "reply_needs_review": "a reply awaits staff confirmation of its question outcomes",
    "reply_unverified": "a reply could not be authenticated",
    "reply_auth_failed": "a reply failed authentication",
    "sender_mismatch": "a reply came from an address other than the verified one",
    "unmatched": "a message matched no sent message",
    "application_closed": "a reply arrived for a closed application",
    "hard_bounce": "a message bounced permanently; automation is paused",
    "loop_threshold": "too many automatic replies; automation is paused",
    "send_outcome_unknown": "a send's outcome is unknown",
    "retries_exhausted": "a send was rejected temporarily too many times",
    "smtp_transport_blocked": "the mail channel is blocked",
    "send_rejected_permanent": "a send was rejected permanently",
    "send_refused": "a send was refused before sending",
    "filed_copy_failed": "a copy could not be filed",
}


def _staff_item_model():
    """The staff-item model, through the reverse relation it declares on Application (no import and no model
    name: correspondence depends on applications, 003 ADR-01)."""
    return Application._meta.get_field("staff_items").related_model


@dataclass(frozen=True)
class Step:
    party: str  # who acts next: Applicant, System, Staff, or Blocked (nobody can act in this slice)
    text: str
    attention: bool = False


def attention_q() -> Q:
    """The staff-attention rule (module docstring) as a filter on applications."""
    working_send = PendingAction.objects.filter(
        kind=SEND_VERIFICATION, status__in=OK_SEND,
        idempotency_key=Concat(Value(f"{SEND_VERIFICATION}:"), Cast(OuterRef("public_id"), CharField())),
    )
    stuck_link = ContactChallenge.objects.filter(
        application=OuterRef("pk"), used_at__isnull=True, superseded_at__isnull=True, expires_at__gt=Now(),
    ).exclude(Exists(working_send))
    next_stage = PendingAction.objects.filter(
        kind=START_EVIDENCE_COLLECTION, subject_type="application", subject_id=OuterRef("public_ref"))
    return (
        Q(Exists(_staff_item_model().objects.filter(application=OuterRef("pk"), status="open")))
        | Q(Exists(AutomationPause.objects.filter(subject_type="application", subject_id=OuterRef("public_ref"))))
        | (Q(contact_verified_at__isnull=True) & ~Q(stage__in=TERMINAL_STAGES) & Q(Exists(stuck_link)))
        | (Q(contact_verified_at__isnull=False) & ~Q(stage__in=TERMINAL_STAGES) & ~Q(Exists(next_stage)))
    )


def actions_for(application):
    return PendingAction.objects.filter(subject_type="application", subject_id=application.public_ref).order_by("created_at", "id")


def attention_items(application):
    return list(application.staff_items.filter(status="open").order_by("opened_at", "id"))


def _event_for(item):
    """S1 attention items name their event (`event:<id>`), which carries the version details."""
    if item.dedupe_key.startswith("event:"):
        return ApplicationEvent.objects.filter(pk=item.dedupe_key.split(":", 1)[1], application=item.application).first()
    return None


def describe_attention(item) -> str:
    event = _event_for(item)
    data = event.data if event is not None and isinstance(event.data, dict) else {}
    text = REASONS.get(item.reason_code, REASONS.get(data.get("reason"), "staff review requested"))
    numbers = data.get("unverified_version_numbers") or ([data["version_number"]] if "version_number" in data else [])
    if numbers:
        text += f" (version {', '.join(str(n) for n in numbers)})"
    return text


def active_challenge(application):
    return (ContactChallenge.objects.filter(application=application, used_at__isnull=True, superseded_at__isnull=True)
            .annotate(unexpired=Q(expires_at__gt=Now())).first())  # expiry by the database clock


def contact_state(application) -> str:
    if application.contact_verified_at is not None:
        return f"Verified at {application.contact_verified_at:%Y-%m-%d %H:%M:%S} UTC by the applicant's confirmation"
    challenge = active_challenge(application)
    if challenge is None:
        return "Not verified; no active verification link"
    if not challenge.unexpired:
        return f"Not verified; the verification link expired at {challenge.expires_at:%Y-%m-%d %H:%M:%S} UTC"
    return f"Not verified; a verification link is active until {challenge.expires_at:%Y-%m-%d %H:%M:%S} UTC"


def adopted_version(application):
    adoption = application.adoptions.select_related("submission_version").first()
    return adoption.submission_version if adoption else None


def next_steps(application) -> list[Step]:
    steps = [Step("Staff", "Review: " + describe_attention(e), attention=True) for e in attention_items(application)]
    paused = AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists()
    if paused:
        steps.append(Step("Staff", "Automation is paused for this application; automated work waits until it is resumed",
                          attention=True))
    if application.stage in TERMINAL_STAGES:
        return steps + [Step("Blocked", f"The application is {application.stage}; nothing further runs")]
    if application.contact_verified_at is None:
        return steps + [_verification_step(application, paused)]
    action = actions_for(application).filter(kind=START_EVIDENCE_COLLECTION).first()
    if action is None:
        return steps + [Step("Staff", "Contact is verified but no start-evidence-collection action exists", attention=True)]
    if application.stage == "evidence":
        return steps + [Step("System", "Evidence is being collected from approved sources (P3)")]
    if application.stage == "assessing":
        return steps + [Step("Blocked", "Evidence collection is complete; the assessment step arrives with P3 task 3B.2")]
    if action.status == PendingAction.Status.HELD:
        return steps + [Step("Blocked", "Start evidence collection is held until the owner releases it (activation command, 018 4.1)")]
    return steps + [Step("Blocked", f"Start evidence collection is {action.status}")]


def _verification_step(application, paused: bool) -> Step:
    challenge = active_challenge(application)
    if challenge is None:
        return Step("Applicant", "No active verification link; a new submission of the form issues one")
    if not challenge.unexpired:
        return Step("Applicant", "The verification link expired; a new submission of the form issues a new one")
    send = PendingAction.objects.filter(idempotency_key=send_verification_key(challenge.public_id)).first()
    Status = PendingAction.Status
    if send is None:
        return Step("Staff", "The active verification link has no send action", attention=True)
    if send.status in (Status.QUEUED, Status.RUNNING):
        if paused:
            return Step("Blocked", "The verification message waits: automation is paused")
        return Step("System", f"The verification message is waiting to be sent (attempt {send.attempts} of {send.max_attempts} so far)")
    if send.status == Status.DONE:
        return Step("Applicant", "Confirm the email address (the message was accepted by the local mail sink, which is not proof of delivery)")
    return Step("Staff", f"The verification send ended {send.status} and is not retried; the applicant has no working link",
                attention=True)
