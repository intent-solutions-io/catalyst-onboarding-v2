"""P4 completion, sequencing and cancellation (021 sections 4 to 6; 4B.2). Synthetic only: the local fake Documenso.

- `enqueue_read`: the one way a read is scheduled. Coalesced per instance (one queued or running read at most) and
  never sooner than a minimum interval after the last read, so webhook floods cannot multiply provider calls
  (TEST-P4-23).
- `ReadAgreement` (`read_agreement`, reads only, automated): a fresh `GET envelope/{id}`, recorded as a read
  observation. Only a read that shows the envelope complete, every required recipient signed, our envelope, key and
  template, and exactly our recipients moves `signing_status` to `signing_complete_verified`; the database refuses that
  move without such an observation in the same transaction (migration 0004). A read on a still-pending envelope
  schedules the next one: the sweep, so a lost webhook only delays completion (TEST-P4-14).
- `AdvanceAgreements` (`advance_agreements`, automated): when a type has passed its gate, re-reads the previous
  envelope at the moment of use (REQ-011) and only then issues the next type (D-15; TEST-P4-01, 06, 31). The P5
  hand-off after the last type is 4B.3.
- `CancelAgreement` (`cancel_agreement`, not redeliverable, runs while paused): cancels an instance at the provider
  with an attempt row and reconciliation (P4-D-18). A completion seen on a cancelled or superseded instance is never
  verified; it opens a staff item (TEST-P4-29).
"""

import hashlib
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Value
from django.db.models.functions import Greatest, Least, Now

from applications import members
from applications.models import Application, Stage
from applications.stages import StageConflict, transition
from correspondence import lapse
from correspondence.models import StaffItem
from correspondence.staff_items import event, open_item
from workflow import journal, ledger
from workflow.models import AutomationPause, PendingAction

from . import provider
from .handlers import (
    CANCEL_UNKNOWN,
    ENVELOPE_MISMATCH,
    PROVIDER_UNAVAILABLE,
    Decision,
    Plan,
    _ProviderStep,
    approved_version,
    paused,
    start_agreement,
)
from .models import (
    AgreementInstance,
    AgreementType,
    EnvelopeAttempt,
    ProviderObservation,
)

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Out = EnvelopeAttempt.Outcome

READ = "read_agreement"
ADVANCE = "advance_agreements"
CANCEL_INSTANCE = "cancel_agreement"

# Staff-item reason codes (identifiers only).
DECLINED = "agreement_declined"  # P4-D-9: automation paused, staff decide
EXPIRED = "agreement_expired"
CANCELLED_AT_PROVIDER = "agreement_cancelled_at_provider"
RECIPIENTS_CHANGED = "agreement_recipients_changed"  # never verified (TEST-P4-31)
COMPLETED_AFTER_CANCEL = (
    "agreement_completed_after_cancel"  # never verified (TEST-P4-29)
)
TEMPLATE_MISSING = "agreement_template_missing"
GATE_READ_FAILED = "agreement_gate_read_failed"

ADVANCE_FAILED = "agreement_advance_failed"
INTEGRITY_HOLD = "agreement_integrity_hold"  # D-43: blocks progression and P5 until a permissioned resolution
REISSUE_NEEDS_DECISION = (
    "agreement_reissue_needs_decision"  # D-42: never reissued without a decision-maker
)
CLOSED_WATCH_ENDED = "agreement_closed_watch_ended"  # D-44: bounded follow-up of a closed instance ended unresolved
DETAILS_NEEDED = "agreement_details_needed"  # POL-18: the next agreement waits for confirmed required details
# 9kg.52: the NDA is referenced (first generation, no instance) but the User Agreement is not covered. The D-15 backstop
# (agreements 0002, 0006) refuses any User Agreement without a verified NDA instance, so nothing is issued: the owner
# decides (record the User Agreement as on file too, or a decided change to D-15).
REFERENCE_BLOCKED = "agreement_reference_needs_decision"
HANDOFF = (
    "provision"  # the held P5 action (021 step 8); no handler exists, so it never runs
)
STOPPED_EVENT = "agreements_stopped"
RESUMED_EVENT = "agreements_resumed"


def _poll() -> timedelta:
    return timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS)


def stopped(application) -> bool:
    """A stop (P4-D-20) holds until a decision-maker resumes it; only a hold can be resumed (4B.2 review)."""
    last = (
        application.events.filter(kind__in=(STOPPED_EVENT, RESUMED_EVENT))
        .order_by("-id")
        .first()
    )
    return last is not None and last.kind == STOPPED_EVENT


# --- observations -------------------------------------------------------------------------------------------------


def _ours(instance) -> list:
    return sorted((r.email.lower(), r.role) for r in instance.recipients.all())


def facts(instance, status: str, recipients, *, identity: bool) -> dict:
    """The allowlisted facts of one provider view: statuses and roles, and whether it is ours. Addresses are compared,
    never stored."""
    ours = _ours(instance)
    theirs = sorted((r.email.lower(), r.role) for r in recipients)
    match = theirs == ours
    required = {
        (r.email.lower(), r.role) for r in instance.recipients.filter(required=True)
    }
    signed = match and all(
        r.signing_status == "SIGNED"
        for r in recipients
        if (r.email.lower(), r.role) in required
    )
    return {
        "envelope_status": status,
        "identity_match": identity,
        "recipients_match": match,
        "all_required_signed": signed and bool(required),
        "recipients": [
            {
                "role": r.role,
                "order": r.signing_order,
                "signing_status": r.signing_status,
                "expired": r.expired,
            }
            for r in recipients
        ],
    }


def observe(
    instance, source: str, data: dict, event_name: str = ""
) -> ProviderObservation | None:
    digest = hashlib.sha256(
        json.dumps({**data, "event": event_name}, sort_keys=True).encode()
    ).hexdigest()
    try:
        with transaction.atomic():
            return ProviderObservation.objects.create(
                instance=instance,
                application=instance.application,
                source=source,
                event=event_name,
                content_sha256=digest,
                **data,
            )
    except IntegrityError:
        return None  # the exact webhook was already recorded: a replay is a no-op (TEST-P4-13)


def read_identity(instance, env: provider.Envelope) -> bool:
    return (
        env.id == instance.envelope_id
        and env.external_id == instance.external_key
        and env.type == "DOCUMENT"
        and env.template_number == instance.template_version.provider_template_number
    )


# --- scheduling a read --------------------------------------------------------------------------------------------


def _due(instance, due_in: timedelta | None):
    """The database clock plus `due_in`, never sooner than the minimum interval after the last read."""
    due = Now() + (due_in or timedelta(0))
    last = (
        ProviderObservation.objects.filter(
            instance=instance, source=ProviderObservation.Source.READ
        )
        .order_by("-observed_at")
        .values_list("observed_at", flat=True)
        .first()
    )
    if last is not None:
        due = Greatest(
            due,
            Value(
                last
                + timedelta(
                    seconds=settings.CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS
                )
            ),
        )
    return due


def enqueue_read(
    instance, *, due_in: timedelta | None = None, closed: bool = False
) -> PendingAction:
    """Inside the caller's transaction with the instance locked. Coalesced onto a queued read, which is brought
    forward when this one is due sooner (a webhook advances the sweep's read); a running read gets one follow-up, so
    a hint arriving mid-read is never lost (4B.2 review). At most one queued read per instance, whatever the flood."""
    due = _due(instance, due_in)
    pending = PendingAction.objects.filter(
        kind=READ, input_ref=str(instance.public_id), status=Status.QUEUED
    ).first()
    if pending is not None:
        PendingAction.objects.filter(pk=pending.pk).update(due_at=Least("due_at", due))
        return pending
    n = (
        PendingAction.objects.filter(
            kind=READ, input_ref=str(instance.public_id)
        ).count()
        + 1
    )
    mode = "closed:" if closed else ""
    return PendingAction.objects.create(
        kind=READ,
        subject_type="application",
        subject_id=instance.application.public_ref,
        input_ref=str(instance.public_id),
        idempotency_key=f"{READ}:{instance.public_id}:{mode}{n}",
        due_at=due,
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS,
    )


def _sweep_on(instance) -> None:
    enqueue_read(
        instance,
        due_in=timedelta(seconds=settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS),
    )


def enqueue_advance(application, authorization: str = "") -> PendingAction:
    """`authorization` ("resume:<event>") is a decision-maker's resume: only then may a type whose earlier instance was
    cancelled or superseded be issued again (D-42). A queued advance takes the authorization over."""
    pending = PendingAction.objects.filter(
        kind=ADVANCE, subject_id=application.public_ref, status=Status.QUEUED
    ).first()
    if pending is not None:
        if authorization:
            PendingAction.objects.filter(pk=pending.pk).update(
                input_ref=authorization, updated_at=Now()
            )
        return pending
    n = (
        PendingAction.objects.filter(
            kind=ADVANCE, subject_id=application.public_ref
        ).count()
        + 1
    )
    return PendingAction.objects.create(
        kind=ADVANCE,
        subject_type="application",
        subject_id=application.public_ref,
        input_ref=authorization or str(application.public_ref),
        idempotency_key=f"{ADVANCE}:{application.public_ref}:{n}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS,
    )


def integrity_hold_open(instance) -> bool:
    return StaffItem.objects.filter(
        reason_code=INTEGRITY_HOLD,
        dedupe_key=f"integrity:{instance.public_id}",
        status=StaffItem.Status.OPEN,
    ).exists()


def open_integrity_hold(instance, reason: str, claim_id=None, actor: str = "") -> None:
    """D-43: the verified fact stays as recorded; this separate hold blocks relying on it."""
    if not integrity_hold_open(instance):
        open_item(
            INTEGRITY_HOLD,
            f"integrity:{instance.public_id}",
            application=instance.application,
            pending_action_id=claim_id,
        )
        event(
            instance.application,
            "agreement_integrity_hold",
            {"instance": str(instance.public_id), "reason": reason},
            actor_ref=actor,
        )


def enqueue_cancel_instance(instance) -> PendingAction:
    n = (
        PendingAction.objects.filter(
            kind=CANCEL_INSTANCE, input_ref=str(instance.public_id)
        ).count()
        + 1
    )
    return PendingAction.objects.create(
        kind=CANCEL_INSTANCE,
        subject_type="application",
        subject_id=instance.application.public_ref,
        input_ref=str(instance.public_id),
        idempotency_key=f"{CANCEL_INSTANCE}:{instance.public_id}:{n}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS,
    )


def _pause(
    application, reason: str
) -> None:  # P4-D-9: decline, expiry and a provider-side cancel
    if not AutomationPause.objects.filter(
        subject_type="application", subject_id=application.public_ref
    ).exists():
        journal.prepare(
            "automation_pause",
            f"pause:{application.public_ref}",
            {"state": "paused", "by": "system"},
        )
        AutomationPause.objects.create(
            subject_type="application",
            subject_id=application.public_ref,
            reason=reason,
            actor_ref="system",
        )
        event(application, "automation_paused", {"by": "system", "reason": reason})
        journal.record(
            "automation_pause",
            f"pause:{application.public_ref}",
            {"state": "paused", "by": "system", "phase": "done"},
        )


# --- the fresh read -------------------------------------------------------------------------------------------------


class ReadAgreement:
    kind = READ
    redeliverable = True  # it reads only
    # D-44: read-only reconciliation is protective and runs while automation is paused or agreements are stopped. A
    # read never issues, distributes, advances or provisions; what it may lead to (advance) is automated and waits.
    automated = False

    def lock_subject(self, claim) -> None:
        application = (
            Application.objects.select_for_update(of=("self",))
            .filter(public_ref=claim.subject_id)
            .first()
        )
        if application is not None:
            AgreementInstance.objects.select_for_update(of=("self",)).filter(
                public_id=claim.input_ref, application=application
            ).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (
            kind == "action_attempts_exhausted"
            or (kind == "action_failed" and data.get("final"))
        ):
            open_item(
                PROVIDER_UNAVAILABLE,
                f"read:{claim.input_ref}",
                application=application,
                pending_action_id=claim.id,
            )
            _keep_sweeping(claim.input_ref)

    def run(self, claim) -> None:
        instance = (
            AgreementInstance.objects.select_related("application", "template_version")
            .filter(public_id=claim.input_ref)
            .first()
        )
        if (
            instance is None
            or str(instance.application.public_ref) != str(claim.subject_id)
            or not instance.envelope_id
        ):
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_read")
            return
        from . import details

        fields = ()
        try:
            env = provider.read(instance.envelope_id)  # outside any transaction
            if (
                env.status == "COMPLETED"
                and instance.issue_status == "issued"
                and instance.signing_status != "signing_complete_verified"
                and details.layout_for(instance.template_version) is not None
            ):
                fields = provider.read_fields(
                    instance.envelope_id
                )  # bgl.8: the typed details, for the read-back alone
        except provider.ProviderError as exc:
            if claim.final:

                def failed():  # staff are told, and the sweep goes on: an outage never ends it (4B.2 review)
                    open_item(
                        PROVIDER_UNAVAILABLE,
                        f"read:{instance.public_id}",
                        application=instance.application,
                        pending_action_id=claim.id,
                    )
                    _keep_sweeping(claim.input_ref)

                ledger.finish(
                    claim, self, status=Status.FAILED, error=exc.code, write=failed
                )
            else:
                due = (
                    timedelta(seconds=exc.retry_after)
                    if exc.retry_after is not None
                    else None
                )
                ledger.finish(
                    claim, self, status=Status.QUEUED, error=exc.code, due_in=due
                )
            return
        ledger.finish(
            claim,
            self,
            status=Status.DONE,
            write=lambda: apply_read(claim, instance.pk, env, fields),
        )


def _keep_sweeping(instance_ref) -> None:
    instance = (
        AgreementInstance.objects.select_related("application")
        .filter(public_id=instance_ref)
        .first()
    )
    if (
        instance is not None
        and instance.issue_status == "issued"
        and instance.envelope_id
        and instance.signing_status
        in ("not_started", "partially_signed", "signing_complete_observed")
    ):
        _sweep_on(instance)


def _closed_follow_up(instance, claim_id) -> None:
    done = PendingAction.objects.filter(
        kind=READ,
        input_ref=str(instance.public_id),
        idempotency_key__contains=":closed:",
    ).count()
    if done < settings.CATALYST_AGREEMENT_ORPHAN_CHECKS:
        enqueue_read(
            instance,
            due_in=timedelta(seconds=settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS),
            closed=True,
        )
    else:  # the provider still shows it open: automatic checking ended with the uncertainty unresolved
        open_item(
            CLOSED_WATCH_ENDED,
            f"closed:{instance.public_id}",
            application=instance.application,
            pending_action_id=claim_id,
        )
        event(
            instance.application,
            "agreement_closed_watch_ended",
            {"instance": str(instance.public_id)},
        )


def apply_read(claim, instance_id: int, env: provider.Envelope, fields=()) -> None:
    """Record one fresh read and move the instance by what it shows (inside the fenced result transaction). `fields`
    are the typed fields read alongside a completed envelope (bgl.8): recorded as the details version on verification."""
    instance = AgreementInstance.objects.select_related(
        "application", "template_version"
    ).get(pk=instance_id)
    application = instance.application
    actor = f"pending_action:{claim.id}"
    data = facts(
        instance, env.status, env.recipients, identity=read_identity(instance, env)
    )
    observe(instance, ProviderObservation.Source.READ, data)
    ref = str(instance.public_id)
    # A follow-up queued while this read ran keeps the minimum interval from this read, not from the one before.
    PendingAction.objects.filter(kind=READ, input_ref=ref, status=Status.QUEUED).update(
        due_at=Greatest(
            "due_at",
            Now()
            + timedelta(seconds=settings.CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS),
        )
    )

    def status(**fields):
        AgreementInstance.objects.filter(pk=instance.pk).update(
            updated_at=Now(), **fields
        )

    if (
        instance.signing_status == "signing_complete_verified"
        and not instance.replaced_at
    ):
        ok = (
            env.status == "COMPLETED"
            and data["identity_match"]
            and data["all_required_signed"]
        )
        if (
            not ok
        ):  # D-43: the earlier verified read stays recorded; reliance on it is blocked
            open_integrity_hold(
                instance,
                "recipients_changed"
                if not data["recipients_match"]
                else "provider_state_changed",
                claim.id,
                actor,
            )
        return
    if instance.replaced_at:
        return  # verified history replaced by a new generation (D-43): not a closed agreement, not a new exception
    if instance.issue_status in ("superseded", "cancelled"):
        if env.status == "COMPLETED":  # TEST-P4-29: never verified, never dropped
            open_item(
                COMPLETED_AFTER_CANCEL,
                f"read:{ref}",
                application=application,
                pending_action_id=claim.id,
            )
            event(
                application,
                "agreement_completed_after_cancel",
                {"instance": ref},
                actor_ref=actor,
            )
        elif env.status in ("PENDING", "DRAFT"):
            _closed_follow_up(
                instance, claim.id
            )  # D-44: bounded, then an explicit end of watch
        return
    if not data["identity_match"]:
        open_item(
            ENVELOPE_MISMATCH,
            f"read:{ref}",
            application=application,
            pending_action_id=claim.id,
        )
        event(
            application, "agreement_read_mismatch", {"instance": ref}, actor_ref=actor
        )
        _keep_sweeping(ref)
        return
    if instance.issue_status in ("cancel_pending", "cancel_uncertain"):
        if env.status == "COMPLETED":  # TEST-P4-29: never verified, never dropped
            open_item(
                COMPLETED_AFTER_CANCEL,
                f"read:{ref}",
                application=application,
                pending_action_id=claim.id,
            )
            event(
                application,
                "agreement_completed_after_cancel",
                {"instance": ref},
                actor_ref=actor,
            )
        elif env.status == "CANCELLED" and instance.issue_status == "cancel_uncertain":
            status(issue_status="cancelled", signing_status="cancelled")
        return
    if (
        instance.issue_status != "issued"
        or instance.signing_status == "signing_complete_verified"
    ):
        return
    if application.stage == Stage.LAPSED and any(
        r.signing_status == "SIGNED" for r in env.recipients
    ):
        # bgl.7: a signature reopens a lapsed application to `agreements` before anything advances (034 row 21)
        lapse.reopen(application, trigger=f"signature:{ref}", actor_ref=actor)
    if env.status == "COMPLETED":
        if data["all_required_signed"]:
            status(signing_status="signing_complete_verified", custody_status="pending")
            event(
                application,
                "agreement_signing_verified",
                {"instance": ref},
                actor_ref=actor,
            )
            from . import details
            from .custody import enqueue_store

            details.capture(
                instance, env, fields, claim.id, actor
            )  # bgl.8: the typed details, once, from this envelope
            enqueue_store(
                instance
            )  # 4B.3: custody next; the advance follows custody where the gate needs it
            enqueue_advance(application)
            return
        status(signing_status="signing_complete_observed")
        reason = (
            RECIPIENTS_CHANGED if not data["recipients_match"] else ENVELOPE_MISMATCH
        )
        open_item(
            reason, f"read:{ref}", application=application, pending_action_id=claim.id
        )
        event(
            application,
            "agreement_completion_not_verified",
            {"instance": ref, "reason": reason},
            actor_ref=actor,
        )
        _keep_sweeping(ref)  # the provider may correct it; keep looking (4B.2 re-check)
        return
    if env.status == "REJECTED" or any(
        r.signing_status == "REJECTED" for r in env.recipients
    ):
        status(signing_status="declined")
        _pause(application, "agreement_declined")  # P4-D-9
        open_item(
            DECLINED, f"read:{ref}", application=application, pending_action_id=claim.id
        )
        event(application, "agreement_declined", {"instance": ref}, actor_ref=actor)
        return
    if env.status == "CANCELLED":
        status(signing_status="cancelled", issue_status="cancelled")
        _pause(application, "agreement_cancelled_at_provider")
        open_item(
            CANCELLED_AT_PROVIDER,
            f"read:{ref}",
            application=application,
            pending_action_id=claim.id,
        )
        event(
            application,
            "agreement_cancelled_at_provider",
            {"instance": ref},
            actor_ref=actor,
        )
        return
    if any(r.expired for r in env.recipients):
        status(signing_status="expired")
        _pause(application, "agreement_expired")
        open_item(
            EXPIRED, f"read:{ref}", application=application, pending_action_id=claim.id
        )
        event(application, "agreement_expired", {"instance": ref}, actor_ref=actor)
        return
    if (
        any(r.signing_status == "SIGNED" for r in env.recipients)
        and instance.signing_status == "not_started"
    ):
        status(signing_status="partially_signed")
    elif instance.signing_status == "signing_complete_observed":
        status(
            signing_status="partially_signed"
            if any(r.signing_status == "SIGNED" for r in env.recipients)
            else "not_started"
        )  # a webhook claimed completion that the read does not show
    from .countersign import after_read

    after_read(
        instance, env
    )  # bgl.9: under the automatic countersignature, the applicant's signature queues it now
    _sweep_on(instance)  # the sweep


# --- the D-15 sequence -----------------------------------------------------------------------------------------------


def required_details(agreement_type) -> list:
    return list(
        settings.CATALYST_AGREEMENT_REQUIRED_DETAILS.get(agreement_type.key, [])
    )


def details_confirmed(application, agreement_type) -> bool:
    """POL-18: a type with required details waits for a confirmed version holding every field."""
    from .models import AgreementDetailsVersion

    fields = required_details(agreement_type)
    if not fields:
        return True
    confirmed = (
        AgreementDetailsVersion.objects.filter(
            application=application,
            agreement_type=agreement_type,
            status=AgreementDetailsVersion.Status.CONFIRMED,
        )
        .order_by("-version")
        .first()
    )
    return confirmed is not None and all(
        str((confirmed.values or {}).get(f, "")).strip() for f in fields
    )


def latest_details_ref(application, agreement_type) -> str:
    from .models import AgreementDetailsVersion

    row = (
        AgreementDetailsVersion.objects.filter(
            application=application,
            agreement_type=agreement_type,
            status=AgreementDetailsVersion.Status.CONFIRMED,
        )
        .order_by("-version")
        .first()
    )
    return str(row.public_id) if row else ""


def _live(application, agreement_type):
    return (
        AgreementInstance.objects.select_related("agreement_type", "template_version")
        .filter(
            application=application,
            agreement_type=agreement_type,
            replaced_at__isnull=True,
        )
        .exclude(issue_status__in=("superseded", "cancelled"))
        .first()
    )


def referenced(application) -> dict:
    """9kg.52 (030 Q4, D-51): {type key: label} for the required types the owner recorded as on file from the first
    generation ("referenced, not re-signed"). A referenced type with no live instance counts as satisfied by the
    reference: it is never issued, it is a distinct "referenced" state and never a verified instance, so the signing,
    custody and countersignature paths do not see it. A type the record does not cover is still issued, with one
    exception the database decides: a User Agreement after a referenced NDA, which the D-15 backstop refuses, opens
    `REFERENCE_BLOCKED` for the owner instead. A live instance, if one exists, governs as before. Counsel's confirmation that the reference covers the type is the
    owner's go/no-go item (029 section 17.2), not a code check."""
    covered = members.covers(application)
    return {
        t.key: covered[t.key]
        for t in AgreementType.objects.filter(required=True, key__in=list(covered))
        if _live(application, t) is None
    }


def prerequisites(application):
    """(refs, digest, reason): the exact agreement prerequisites for provisioning, and an empty reason when they all
    hold. One function for the P4 hand-off and every P5 effect boundary (023 section 11.4), from the database only;
    a fresh provider read is the caller's, outside any transaction."""
    _, next_type, reason = next_step(application)
    types = list(AgreementType.objects.filter(required=True).order_by("order"))
    if next_type is not None or reason != "all_passed":
        return {}, "", reason or "agreements_incomplete"
    covered = referenced(application)
    if any(
        not details_confirmed(application, t) for t in types if t.key not in covered
    ):
        return {}, "", "details_needed"
    refs = {}
    record = members.on_file(application) if covered else None
    for t in types:
        if (
            t.key in covered
        ):  # 9kg.52: the reference, never an instance; a correction changes the digest
            refs[t.key] = {
                "referenced": covered[t.key],
                "record": str(record.public_id),
            }
            continue
        live = (
            AgreementInstance.objects.filter(
                application=application, agreement_type=t, replaced_at__isnull=True
            )
            .exclude(issue_status__in=("superseded", "cancelled"))
            .get()
        )
        refs[t.key] = {
            "instance": str(live.public_id),
            "documents": sorted(
                str(d) for d in live.documents.values_list("public_id", flat=True)
            ),
            "details": latest_details_ref(application, t),
        }
    digest = hashlib.sha256(json.dumps(refs, sort_keys=True).encode()).hexdigest()
    return refs, digest, ""


def live_required_instances(application) -> list:
    """The live instance of every required type that is not referenced (9kg.52); None where one is missing."""
    covered = referenced(application)
    return [
        _live(application, t)
        for t in AgreementType.objects.filter(required=True).order_by("order")
        if t.key not in covered
    ]


def fresh_read_problem(application) -> str:
    """Outside any transaction: a fresh provider read of every live required agreement must still show it complete,
    ours, with every required signature (REQ-011; 023 section 11.4). A mismatch opens the D-43 integrity hold. Returns
    a reason code, or an empty string."""
    if transaction.get_connection().in_atomic_block:
        raise RuntimeError("a fresh provider read never runs inside a transaction")
    for instance in live_required_instances(application):
        if instance is None or not instance.envelope_id:
            return "agreements_incomplete"
        try:
            env = provider.read(instance.envelope_id)
        except provider.ProviderError:
            return "provider_unavailable"
        data = facts(
            instance, env.status, env.recipients, identity=read_identity(instance, env)
        )
        if not (
            env.status == "COMPLETED"
            and data["identity_match"]
            and data["all_required_signed"]
        ):
            with transaction.atomic():
                Application.objects.select_for_update(of=("self",)).get(
                    pk=application.pk
                )
                observe(instance, ProviderObservation.Source.READ, data)
                open_integrity_hold(instance, "provisioning_read_mismatch")
            return "agreement_integrity_hold"
    return ""


def gate_passed(instance) -> bool:
    if (
        instance.signing_status != "signing_complete_verified"
        or instance.replaced_at
        or integrity_hold_open(instance)
    ):
        return False
    return (
        instance.agreement_type.gate == AgreementType.Gate.SIGNING
        or instance.custody_status == "stored_verified"
    )


def next_step(application):
    """(previous instance or None, next type or None, reason). The next type is the first, by order, without a live
    instance (not superseded, cancelled or replaced); every type before it must have passed its gate. The reason is
    "reissue" when that type had an earlier instance: issuing it again needs a decision-maker (D-42). A type the
    member's first-generation record covers (`referenced`) is skipped: never issued (9kg.52)."""
    previous = None
    covered = referenced(application)
    for agreement_type in AgreementType.objects.filter(required=True).order_by("order"):
        from firstgen.agreements import unadopted, WAITING
        from firstgen.mapping import COMPLETED_AGREEMENT

        legacy_envelopes = unadopted(application, agreement_type.key)
        if any(
            record.data.get("status") not in COMPLETED_AGREEMENT
            for record in legacy_envelopes
        ):
            return previous, None, WAITING
        if agreement_type.key in covered:
            continue  # 9kg.52: satisfied by the first-generation reference; `previous` stays the last real instance
        of_type = AgreementInstance.objects.select_related(
            "agreement_type", "template_version"
        ).filter(application=application, agreement_type=agreement_type)
        live = (
            of_type.exclude(issue_status__in=("superseded", "cancelled"))
            .filter(replaced_at__isnull=True)
            .first()
        )
        if live is None:
            if legacy_envelopes:
                return previous, None, WAITING
            return previous, agreement_type, "reissue" if of_type.exists() else ""
        if not gate_passed(live):
            return previous, None, "waiting_for_gate"
        previous = live
    return previous, None, "all_passed"


class AdvanceAgreements:
    kind = ADVANCE
    redeliverable = True
    automated = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(
            public_ref=claim.subject_id
        ).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (
            kind == "action_attempts_exhausted"
            or (kind == "action_failed" and data.get("final"))
        ):
            open_item(
                ADVANCE_FAILED,
                f"advance:{application.public_ref}",
                application=application,
                pending_action_id=claim.id,
            )

    def run(self, claim) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if (
            application is None
            or application.stage != Stage.AGREEMENTS
            or stopped(application)
        ):
            ledger.finish(claim, self, status=Status.DONE, error="not_advancing")
            return
        if paused(application):
            ledger.finish(
                claim,
                self,
                status=Status.QUEUED,
                error="automation_paused",
                refund_attempt=True,
                due_in=_poll(),
            )
            return
        previous, next_type, reason = next_step(application)
        env = None
        if next_type is None:
            ledger.finish(
                claim,
                self,
                status=Status.DONE,
                error=reason,
                write=(lambda: self.hand_off(claim, application))
                if reason == "all_passed"
                else None,
            )
            return
        if next_type.key == "user_agreement" and "nda" in referenced(application):
            ledger.finish(
                claim,
                self,
                status=Status.DONE,
                error="reference_needs_decision",
                write=lambda: (
                    open_item(
                        REFERENCE_BLOCKED,
                        f"advance:{application.public_ref}:{next_type.key}",
                        application=application,
                        pending_action_id=claim.id,
                    ),
                    event(
                        application,
                        "agreement_reference_needs_decision",
                        {"type": next_type.key},
                        actor_ref=f"pending_action:{claim.id}",
                    ),
                ),
            )
            return
        if not details_confirmed(application, next_type):
            ledger.finish(
                claim,
                self,
                status=Status.DONE,
                error="details_needed",
                write=lambda: open_item(
                    DETAILS_NEEDED,
                    f"details:{application.public_ref}:{next_type.key}",
                    application=application,
                    pending_action_id=claim.id,
                ),
            )
            return
        late = StaffItem.objects.filter(
            application=application,
            reason_code=COMPLETED_AFTER_CANCEL,
            status=StaffItem.Status.OPEN,
        ).exists()
        if reason == "reissue" and (late or not claim.input_ref.startswith("resume:")):
            # D-42: never reissued without a decision-maker, and never while the provider shows an earlier one
            # completed after its cancel (QA review)
            ledger.finish(
                claim,
                self,
                status=Status.DONE,
                error="reissue_needs_decision",
                write=lambda: open_item(
                    REISSUE_NEEDS_DECISION,
                    f"advance:{application.public_ref}:{next_type.key}",
                    application=application,
                    pending_action_id=claim.id,
                ),
            )
            return
        if previous is not None:
            try:  # REQ-011: the previous agreement is re-read at the moment the next one is issued
                env = provider.read(previous.envelope_id)
            except provider.ProviderError as exc:
                if claim.final:
                    ledger.finish(
                        claim,
                        self,
                        status=Status.FAILED,
                        error=exc.code,
                        write=lambda: open_item(
                            GATE_READ_FAILED,
                            f"advance:{application.public_ref}",
                            application=application,
                            pending_action_id=claim.id,
                        ),
                    )
                else:
                    ledger.finish(claim, self, status=Status.QUEUED, error=exc.code)
                return
        ledger.finish(
            claim,
            self,
            status=Status.DONE,
            write=lambda: self.issue(claim, application, previous, next_type, env),
        )

    def hand_off(self, claim, application) -> None:
        """021 step 8: every required agreement has passed its gate (signing and custody by default) and every required
        detail is confirmed. Re-checked here under the application lock; the compare-and-set stage move and the unique
        action key mean a duplicate or stale advance creates nothing more."""
        application = Application.objects.get(pk=application.pk)
        if application.stage != Stage.AGREEMENTS or stopped(application):
            return
        refs, digest, reason = prerequisites(application)
        if reason:
            return
        try:
            transition(
                application.pk,
                (Stage.AGREEMENTS,),
                Stage.AGREEMENTS_COMPLETE,
                event_kind="agreements_complete",
                data={"prerequisites": refs, "digest": digest},
                actor_ref=f"pending_action:{claim.id}",
            )
        except StageConflict:
            return
        handoff = PendingAction.objects.create(
            kind=HANDOFF,
            subject_type="application",
            subject_id=application.public_ref,
            input_ref=f"agreements:{digest}",
            idempotency_key=f"{HANDOFF}:{application.public_ref}",
            status=Status.HELD,
        )
        if (
            settings.CATALYST_RELEASE_MODE == "automatic"
        ):  # bgl.9: the release runs without a person (decision 13)
            from provisioning.auto_release import enqueue as enqueue_release

            enqueue_release(application, handoff)

    def issue(self, claim, application, previous, next_type, env) -> None:
        actor = f"pending_action:{claim.id}"
        application = Application.objects.get(pk=application.pk)
        if application.stage != Stage.AGREEMENTS or stopped(application):
            return
        _, now_type, _ = next_step(application)  # re-checked under the lock
        if now_type is None or now_type.pk != next_type.pk:
            return
        if previous is not None:
            previous = AgreementInstance.objects.select_related(
                "application", "template_version"
            ).get(pk=previous.pk)
            data = facts(
                previous,
                env.status,
                env.recipients,
                identity=read_identity(previous, env),
            )
            observe(previous, ProviderObservation.Source.READ, data)
            if not (
                env.status == "COMPLETED"
                and data["identity_match"]
                and data["all_required_signed"]
            ):
                # TEST-P4-31, D-43: nothing is issued on a stale verification; reliance on it is held for resolution
                open_integrity_hold(
                    previous,
                    "recipients_changed"
                    if not data["recipients_match"]
                    else "provider_state_changed",
                    claim.id,
                    actor,
                )
                event(
                    application,
                    "agreement_gate_read_refused",
                    {"instance": str(previous.public_id)},
                    actor_ref=actor,
                )
                return
        version = approved_version(next_type.key)
        if version is None:
            open_item(
                TEMPLATE_MISSING,
                f"advance:{application.public_ref}:{next_type.key}",
                application=application,
                pending_action_id=claim.id,
            )
            return
        try:
            start_agreement(application, version, actor)
        except (
            ValueError
        ) as exc:  # the contact is no longer verified: staff decide (4B.2 review)
            open_item(
                ADVANCE_FAILED,
                f"advance:{application.public_ref}",
                application=application,
                pending_action_id=claim.id,
            )
            event(
                application,
                "agreement_advance_refused",
                {"reason": str(exc)},
                actor_ref=actor,
            )


# --- cancelling an instance at the provider (P4-D-18) ------------------------------------------------------------------


class CancelAgreement(_ProviderStep):
    kind = CANCEL_INSTANCE
    step = EnvelopeAttempt.Step.CANCEL
    uncertain_status = "cancel_uncertain"
    automated = False  # protective: it runs while automation is paused

    def check(self, claim):
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        instance = (
            AgreementInstance.objects.select_related("application", "template_version")
            .filter(public_id=claim.input_ref)
            .first()
        )
        if (
            application is None
            or instance is None
            or instance.application_id != application.pk
        ):
            return Decision(Status.FAILED, "instance_not_found"), None
        pending = self._pending(instance, instance.external_key)
        if pending:
            return self._to_reconcile(claim, instance, pending), None
        if instance.issue_status != "cancel_pending" or not instance.envelope_id:
            return Decision(Status.DONE, "not_pending"), None
        if not provider.configured():
            return Decision(
                Status.FAILED,
                "provider_not_configured",
                write=lambda: open_item(
                    CANCEL_UNKNOWN,
                    f"cancel:{instance.public_id}",
                    application=application,
                    pending_action_id=claim.id,
                ),
            ), None
        attempt = self._attempt(claim, instance, envelope_id=instance.envelope_id)
        return None, Plan(
            attempt.pk,
            instance.pk,
            envelope_id=instance.envelope_id,
            external_key=instance.external_key,
        )

    def call(self, plan: Plan):
        try:
            current = provider.read(plan.envelope_id)
        except provider.ProviderError as exc:
            raise provider.ProviderError(
                exc.code, sent=False, status=exc.status
            ) from None
        if current.external_id != plan.external_key:
            return "mismatch"
        if current.status in ("CANCELLED", "REJECTED"):
            return "already_closed"
        if current.status == "DRAFT":
            return "left_draft"  # never sent: nobody can sign it; the installed API cannot cancel a draft
        if current.status == "COMPLETED":
            return "completed"
        provider.cancel(plan.envelope_id)
        return "cancelled"

    def record_result(self, claim, plan: Plan, result) -> bool:
        if isinstance(result, provider.ProviderError):
            return self.record_failure(claim, plan, result)
        instance = AgreementInstance.objects.select_related("application").get(
            pk=plan.instance_id
        )
        actor = f"pending_action:{claim.id}"

        def write():
            closed = result in ("cancelled", "already_closed", "left_draft")
            self._finish_attempt(
                plan.attempt_id,
                Out.SUCCEEDED
                if result in ("cancelled", "already_closed")
                else Out.NOT_SENT,
                result,
            )
            if closed:
                AgreementInstance.objects.filter(
                    pk=instance.pk, issue_status="cancel_pending"
                ).update(
                    issue_status="cancelled",
                    signing_status="cancelled",
                    updated_at=Now(),
                )
                if (
                    result == "left_draft"
                ):  # D-44: a draft left at the provider gets bounded follow-up reads
                    from .handlers import _watch_left_draft

                    _watch_left_draft(instance)
            else:
                reason = (
                    COMPLETED_AFTER_CANCEL
                    if result == "completed"
                    else ENVELOPE_MISMATCH
                )
                AgreementInstance.objects.filter(
                    pk=instance.pk, issue_status="cancel_pending"
                ).update(issue_status="failed_needs_staff", updated_at=Now())
                open_item(
                    reason,
                    f"cancel:{instance.public_id}",
                    application=instance.application,
                    pending_action_id=claim.id,
                )
            event(
                instance.application,
                "agreement_cancel",
                {"instance": str(instance.public_id), "result": result},
                actor_ref=actor,
            )

        return ledger.finish(
            claim,
            self,
            status=Status.DONE if result != "mismatch" else Status.FAILED,
            error=result,
            write=write,
        )
