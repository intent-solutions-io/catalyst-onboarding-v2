"""What the staff dossier says about one application (005 S1.2 Staff; S1-T7). Derived only from existing
records, read-only, and never from or about a token: challenges are described by their state and times,
pending actions by kind and status (their inputs and idempotency keys name challenge ids, so they are not
shown).

Staff attention, one rule for the dossier, the list column and the list filter (`attention_q`):
- an event of kind `needs_staff_attention` (005 S1.4; resolving one arrives in P2, so each stays open);
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
from .models import TERMINAL_STAGES, ApplicationEvent, ContactChallenge
from .services import SEND_VERIFICATION, send_verification_key

ATTENTION = "needs_staff_attention"
OK_SEND = (PendingAction.Status.QUEUED, PendingAction.Status.RUNNING, PendingAction.Status.DONE)
REASONS = {
    "repeat_after_verification": "a submission arrived after the address was verified; it was not adopted",
    "newer_unverified_version": "a newer submission exists than the one the applicant confirmed",
}


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
        Q(Exists(ApplicationEvent.objects.filter(application=OuterRef("pk"), kind=ATTENTION)))
        | Q(Exists(AutomationPause.objects.filter(subject_type="application", subject_id=OuterRef("public_ref"))))
        | (Q(contact_verified_at__isnull=True) & ~Q(stage__in=TERMINAL_STAGES) & Q(Exists(stuck_link)))
        | (Q(contact_verified_at__isnull=False) & ~Q(stage__in=TERMINAL_STAGES) & ~Q(Exists(next_stage)))
    )


def actions_for(application):
    return PendingAction.objects.filter(subject_type="application", subject_id=application.public_ref).order_by("created_at", "id")


def attention_items(application):
    return list(application.events.filter(kind=ATTENTION).order_by("occurred_at", "id"))


def describe_attention(event: ApplicationEvent) -> str:
    data = event.data if isinstance(event.data, dict) else {}
    text = REASONS.get(data.get("reason"), "staff review requested")
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
    if action.status == PendingAction.Status.HELD:
        return steps + [Step("Blocked", "Start evidence collection is held: no step after confirmation exists in this slice")]
    return steps + [Step("Blocked", f"Start evidence collection is {action.status}; no step after confirmation exists in this slice")]


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
