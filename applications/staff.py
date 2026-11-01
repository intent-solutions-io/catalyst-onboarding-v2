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
- once contact is verified: no next-stage action;
- an application awaiting the qualification decision or on hold (the decision-maker owes the next step).
Every other next step belongs to the applicant, the system, or nobody (blocked: the step waits on a policy
decision or the owner's release, and the dossier says which).
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
    "repeat_after_decline": "a submission arrived after the application was declined; it was not adopted and nothing new was created",
    "newer_unverified_version": "a newer submission exists than the one the applicant confirmed",
    "contact_verified_existing_workflow": "contact is now verified; review the existing workflow before continuing it",
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
    "assessment_failed": "an assessment run failed; staff may rerun it or record a human-only assessment",
    "assessment_capped": "the assessment budget for this snapshot is spent; the human-only decision form is the way on",
    "assessment_input_changed": "the assessment input changed before the run; a reassessment was needed",
    "assessment_pack_refused": "the prompt pack was refused; no assessment can run",
    "assessment_suspended": "refused by suspension: model advice is disabled, a human-only assessment applies (oc4.12)",
    # 9kg.41: plain words for the launch's other common items (the dossier and the staff item page share them)
    "escalate_unanswered": "a question stayed unanswered after the last reminder",
    # bgl.7: the lapse after the last reminder and the signing reminder
    "lapse_note_refused": "the application should lapse but its closing note could not be prepared (no approved wording"
                          " or no verified address); it looks again by itself",
    "lapse_failed": "the lapse could not be recorded; the application still waits",
    "signing_reminder_unavailable": "a signing reminder was due but the service has no way to send the signing link"
                                    " again yet; the applicant was not reminded",
    "signing_reminder_refused": "a signing reminder could not be prepared (the recipient is not the verified address)",
    "signing_reminder_failed": "the signing reminder could not be recorded",
    "evidence_required_unavailable": "a required evidence item could not be read; re-fetch it or proceed without it",
    "claims_missing": "the adopted submission carries no claim fields; a new submission with claims is needed",
    "agreement_declined": "an agreement was declined at the provider; automation is paused",
    "agreement_expired": "an agreement expired at the provider; automation is paused",
    "agreement_cancelled_at_provider": "an agreement was cancelled at the provider; automation is paused",
    "agreement_create_unknown": "an agreement's creation outcome is unknown; a decision-maker decides on the agreements screen",
    "agreement_distribute_unknown": "an agreement's sending outcome is unknown; a decision-maker decides on the agreements screen",
    "agreement_cancel_unknown": "an agreement's cancel outcome is unknown; a decision-maker cancels again on the agreements screen",
    "agreement_integrity_hold": "a signed agreement no longer matches what was verified; it is held",
    "agreement_custody_failed": "the signed copy could not be stored; retry custody on the agreements screen",
    "agreement_provider_unavailable": "the signing provider could not be reached",
    # bgl.8 (034 rows 27, 32, 33): the service-sent link, the read-back of typed details and their address quality
    "agreement_link_send_failed": "the signing-link mail could not be sent, or the applicant was not found on the envelope;"
                                  " check the agreements screen and the provider",
    "agreement_details_readback_incomplete": "not every detail could be read back from the signed agreement; record the"
                                             " details on the agreements screen from the signed copy",
    "agreement_address_quality": "the address typed on the signed agreement looks incomplete or its postal code does not fit"
                                 " its country; nothing is blocked, check it on the agreements screen",
    "provisioning_activation_blocked": "activation is blocked; fix the cause, then retry activation",
    "decline_not_notified": "the decline notice bounced permanently; the applicant was not notified",  # oc4.11
    "decline_notice_refused": "the decline notice could not be prepared. If its wording is not approved for this"
                              " environment or there is no verified address, it looks again by itself and this item"
                              " reopens after an acknowledgement while that stays so; if its attempts ran out, it does"
                              " not retry and the applicant must be told another way",  # oc4.11
    "decline_notice_member_on_file": "no decline notice was sent: a first-generation agreement was recorded on file"
                                     " after the decline; the decline needs the owner's review (030 Q8)",  # oc4.11
    "verification_expired": "the applicant's only verification link expired before they confirmed; no working link is out",
    "agreement_reference_needs_decision": "the NDA is on file from the first generation but the User Agreement is not;"
                                          " nothing is issued until the owner decides",  # 9kg.52, D-15
    # bgl.14: the Twenty projection's review cases (crm.projection.REVIEW_REASONS; the first generation's crm_review_item)
    "twenty_ambiguous_match": "several Twenty people match this application; link the right one (catalyst_twenty_link)",
    "twenty_person_linked_elsewhere": "the Twenty person that matches is linked to another open application",
    "twenty_linked_person_missing": "the linked Twenty person no longer exists; link another (catalyst_twenty_link)",
    "twenty_field_overwritten": "a field someone edited in Twenty was overwritten by the projection",
    "twenty_request_rejected": "Twenty refused a projection request; it is not retried",
    "twenty_projection_failed": "the Twenty projection failed after its last attempt",
}


# 9kg.41 (029 section 5.2, "Actions enqueued without a handler"; audit 8.8): an action held on purpose, waiting on a
# policy decision or the owner's release, says so in the dossier instead of a bare "held". Kind names only, never an
# import: applications depends on no later app (003 ADR-01). Any other held action is an operational hold whose reason
# code the dossier shows as its last error.
HELD_ON_POLICY = {
    "start_evidence_collection": "waits for the owner's release (activate_evidence_collection, 018 4.1)",
    "issue_nda": "waits for the owner's release (activate_agreements, 021 section 2)",
    "interpret_reply": "model reading of replies is off; staff confirm the outcome on the reply screen, which ends it",
    "provision": "waits for the owner's release (activate_provisioning, 023 section 5); off at the internal launch",
}


def describe_status(action) -> str:
    """The status the dossier shows for one pending action: a held action waiting on policy is labelled as such."""
    if action.status == PendingAction.Status.HELD and action.kind in HELD_ON_POLICY:
        return f"held on policy: {HELD_ON_POLICY[action.kind]}"
    return action.status


def _staff_item_model():
    """The staff-item model, through the reverse relation it declares on Application (no import and no model
    name: correspondence depends on applications, 003 ADR-01)."""
    return Application._meta.get_field("staff_items").related_model


@dataclass(frozen=True)
class Step:
    party: str  # who acts next: Applicant, System, Staff, or Blocked (waits on a policy decision or the owner's release)
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
        | Q(stage__in=("awaiting_decision", "on_hold"))  # a decision is owed (9kg.50 review)
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
        if application.staff_items.filter(status="open", reason_code__in=("assessment_suspended", "assessment_capped")).exists():
            return steps + [Step("Staff", "The assessment is refused by suspension or capped: record a human-only decision on the"
                                 " decision screen", attention=True)]
        return steps + [Step("System", "Assessing: a run is queued or waiting; a failed run opens a staff item")]
    if application.stage == "awaiting_decision":  # 9kg.50 review: the decision-maker owes the next step
        return steps + [Step("Staff", "Awaiting the qualification decision: record it on the decision screen", attention=True)]
    if application.stage == "on_hold":
        return steps + [Step("Staff", "On hold: the way on is an admit or a decline on the decision screen", attention=True)]
    if application.stage == "lapsed":  # bgl.7: quiet, not closed
        return steps + [Step("Applicant", "Lapsed after the last reminder went unanswered; a reply or a signature reopens it")]
    if action.status == PendingAction.Status.HELD:
        return steps + [Step("Blocked", "Start evidence collection is held until the owner releases it (activation command, 018 4.1)")]
    return steps + [Step("Blocked", f"Start evidence collection is {action.status}")]


def _verification_step(application, paused: bool) -> Step:
    challenge = active_challenge(application)
    if challenge is None:
        return Step("Applicant", "No active verification link; a new submission of the form issues one")
    if not challenge.unexpired:
        return Step("Applicant", "The verification link expired; a new submission of the form issues a new one"
                    " (or staff resend it from the correspondence screen)")
    send = PendingAction.objects.filter(idempotency_key=send_verification_key(challenge.public_id)).first()
    Status = PendingAction.Status
    if send is None:
        return Step("Staff", "The active verification link has no send action", attention=True)
    if send.status in (Status.QUEUED, Status.RUNNING):
        if paused:
            return Step("Blocked", "The verification message waits: automation is paused")
        return Step("System", f"The verification message is waiting to be sent (attempt {send.attempts} of {send.max_attempts} so far)")
    if send.status == Status.DONE:
        return Step("Applicant", "Confirm the email address (the message was accepted by the configured mail backend, which is not proof of"
                    " delivery)")
    return Step("Staff", f"The verification send ended {send.status} and is not retried; the applicant has no working link"
                " (staff can resend it from the correspondence screen)", attention=True)
