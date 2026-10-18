"""Staff services for P4 agreements (021 sections 5 and 9; 4B.1). One transaction each, the application locked first.

- `approve_template_version`: the owner approves one template version (POL-07; P4-D-1). Approving twice does nothing
  more; an approved version is never edited (database trigger).
- `decide_uncertain_create`: a decision-maker decides an unknown create that reconciliation could not settle
  (P4-D-8): mark it not sent and allow one new create under a **new** key, or abandon the agreement. The old key stays
  watched, so a late envelope is caught as an orphan and never verified (P4-D-19). A decision never rewrites the
  unknown outcome into a known one: the attempt records `decided_not_sent` or `abandoned`.

The permissions are assigned to no group by migration (021 section 9): they are granted to named people.
"""

import hashlib

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent, Stage
from correspondence.models import StaffItem
from correspondence.common import Refused as NoteRefused
from correspondence.staff_items import clean_note as _clean_note, event, resolve_item
from workflow.models import PendingAction

from . import handlers
from .models import AgreementInstance, AgreementTemplateVersion, EnvelopeAttempt

CHOICES = ("not_sent", "abandon")


class Refused(Exception):
    """A service refused; the message is a reason code."""


def clean_note(text: str) -> str:
    try:
        return _clean_note(text)
    except NoteRefused as exc:
        raise Refused(str(exc)) from None


def _final_stop(application):
    """The latest withdrawal or closure not followed by a resume, if any: those are final here (POL-12, P5)."""
    from .completion import RESUMED_EVENT, STOPPED_EVENT

    for row in application.events.filter(kind__in=(STOPPED_EVENT, RESUMED_EVENT)).order_by("-id"):
        if row.kind == RESUMED_EVENT:
            return None
        if (row.data or {}).get("reason") != "on_hold":
            return row
    return None


def _open_for_new_work(application) -> None:
    """Refused unless a new agreement may be issued now: the stage is agreements, nothing is stopped, automation is
    not paused (PR #42 reviews)."""
    from .completion import stopped

    if application.stage != Stage.AGREEMENTS or stopped(application):
        raise Refused("agreements_not_open")
    if handlers.paused(application):
        raise Refused("automation_paused")


def _earlier_types_passed(application, agreement_type) -> None:
    """D-15 and D-43: a later agreement is issued only while every earlier one passes its gate (no integrity hold)."""
    from .completion import gate_passed
    from .models import AgreementType

    for earlier in AgreementType.objects.filter(required=True, order__lt=agreement_type.order):
        live = (AgreementInstance.objects.filter(application=application, agreement_type=earlier, replaced_at__isnull=True)
                .exclude(issue_status__in=("superseded", "cancelled")).first())
        if live is None or not gate_passed(live):
            raise Refused("earlier_agreement_not_passed")


def can(user, permission: str) -> bool:
    return (user is not None and user.is_authenticated and user.is_active and user.is_staff and not user.is_superuser
            and user.has_perm(f"agreements.{permission}"))


def require(user, permission: str) -> None:
    if not can(user, permission):
        raise PermissionDenied(permission)


def approve_template_version(version_id: int, user, expected_sha256: str) -> AgreementTemplateVersion:
    require(user, "approve_agreement_template")
    with transaction.atomic():
        version = AgreementTemplateVersion.objects.select_for_update(of=("self",)).get(pk=version_id)
        if expected_sha256 != version.pdf_sha256:
            raise Refused("template_changed_since_shown")
        if version.status == AgreementTemplateVersion.Status.APPROVED:
            return version
        AgreementTemplateVersion.objects.filter(pk=version.pk, status=AgreementTemplateVersion.Status.DRAFT).update(
            status=AgreementTemplateVersion.Status.APPROVED, approved_by=f"user:{user.pk}", approved_at=Now())
    version.refresh_from_db()
    return version


def decide_uncertain_create(instance_id: int, user, choice: str) -> AgreementInstance:
    require(user, "decide_uncertain_agreement")
    if choice not in CHOICES:
        raise Refused("unknown_choice")
    actor = f"user:{user.pk}"
    instance = AgreementInstance.objects.get(pk=instance_id)
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=instance.application_id)
        instance = AgreementInstance.objects.select_for_update(of=("self",)).get(pk=instance_id)
        if instance.issue_status != "create_uncertain":
            raise Refused("not_uncertain")
        attempt = EnvelopeAttempt.objects.filter(instance=instance, step=EnvelopeAttempt.Step.CREATE,
                                                 external_key=instance.external_key,
                                                 outcome=EnvelopeAttempt.Outcome.UNKNOWN).order_by("-id").first()
        if attempt is None:
            raise Refused("no_unknown_attempt")
        if StaffItem.objects.filter(reason_code=handlers.DUPLICATE_ENVELOPES, dedupe_key=f"create:{attempt.public_id}",
                                    status=StaffItem.Status.OPEN).exists():
            raise Refused("duplicate_envelopes_open")  # more than one envelope carries this key: never a third
        if PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref=str(attempt.public_id),
                                        status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists():
            raise Refused("reconciliation_in_progress")  # decide only once the evidence checks have ended
        outcome = EnvelopeAttempt.Outcome.DECIDED_NOT_SENT if choice == "not_sent" else EnvelopeAttempt.Outcome.ABANDONED
        EnvelopeAttempt.objects.filter(pk=attempt.pk).update(outcome=outcome, finished_at=Now())
        PendingAction.objects.filter(kind=handlers.CREATE, input_ref=str(instance.public_id),
                                     status=PendingAction.Status.UNCERTAIN).update(
            status=PendingAction.Status.DONE, last_error=f"decided_{choice}", completed_at=Now(), updated_at=Now())
        if choice == "not_sent" and application.stage == Stage.AGREEMENTS:
            instance.external_key = handlers.new_key()  # P4-D-19: never the same key twice
            AgreementInstance.objects.filter(pk=instance.pk).update(external_key=instance.external_key,
                                                                    issue_status="create_pending", updated_at=Now())
            handlers.enqueue_create(instance)
        else:
            AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="cancelled", updated_at=Now())
        handlers.enqueue_reconcile(attempt, 1, watch=True)
        for item in StaffItem.objects.filter(reason_code=handlers.CREATE_UNKNOWN, dedupe_key=f"create:{attempt.public_id}",
                                             status=StaffItem.Status.OPEN):
            resolve_item(item, code=f"decided_{choice}", actor_ref=actor, effects={"instance": str(instance.public_id)})
        event(application, "agreement_create_decided", {"instance": str(instance.public_id), "choice": choice,
                                                        "attempt": str(attempt.public_id)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    instance.refresh_from_db()
    return instance


# --- 4B.2: cancel, reissue, stop and the unknown distribute (021 section 4; P4-D-9, P4-D-18, P4-D-20) ------------------

STOP_REASONS = ("withdrawn", "closed", "on_hold")
LIVE = ("held", "create_pending", "create_uncertain", "distribute_pending", "distribute_uncertain", "issued",
        "failed_needs_staff")


def _lock(instance_id):
    instance = AgreementInstance.objects.get(pk=instance_id)
    application = Application.objects.select_for_update(of=("self",)).get(pk=instance.application_id)
    return application, AgreementInstance.objects.select_for_update(of=("self",)).get(pk=instance_id)


def _in_flight(instance) -> bool:
    return PendingAction.objects.filter(kind__in=(handlers.CREATE, handlers.DISTRIBUTE, "cancel_agreement"),
                                        input_ref=str(instance.public_id), status=PendingAction.Status.RUNNING).exists()


def _close(instance, actor) -> str:
    """Inside the caller's transaction. An instance with an envelope is cancelled at the provider (P4-D-18); one
    without is closed here, and an unknown create is set aside with its key watched, so a late envelope is cancelled
    as an orphan (P4-D-19). Returns what was done."""
    from .completion import enqueue_cancel_instance

    if instance.signing_status == "signing_complete_verified":
        raise Refused("agreement_already_signed")  # a signed agreement is never cancelled here
    if _in_flight(instance):
        # D-42: a stop must not be forgotten because an exchange is running. The request is recorded once; the
        # exchange records its own result first (a request already sent may have taken effect) and then routes to
        # cancellation instead of continuing (agreements.handlers.cancel_requested).
        AgreementInstance.objects.filter(pk=instance.pk, cancel_requested_at__isnull=True).update(
            cancel_requested_at=Now(), updated_at=Now())
        return "cancel_requested"
    if instance.envelope_id:
        AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="cancel_pending", updated_at=Now())
        enqueue_cancel_instance(instance)
        return "cancel_pending"
    for attempt in EnvelopeAttempt.objects.filter(instance=instance, step=EnvelopeAttempt.Step.CREATE,
                                                  outcome__in=(EnvelopeAttempt.Outcome.SENDING, EnvelopeAttempt.Outcome.UNKNOWN)):
        EnvelopeAttempt.objects.filter(pk=attempt.pk).update(outcome=EnvelopeAttempt.Outcome.ABANDONED, finished_at=Now())
        handlers.enqueue_reconcile(attempt, 1, watch=True)
        for item in StaffItem.objects.filter(reason_code=handlers.CREATE_UNKNOWN, dedupe_key=f"create:{attempt.public_id}",
                                             status=StaffItem.Status.OPEN):
            resolve_item(item, code="abandoned_by_stop", actor_ref=actor, effects={"instance": str(instance.public_id)})
    PendingAction.objects.filter(kind=handlers.CREATE, input_ref=str(instance.public_id),
                                 status=PendingAction.Status.UNCERTAIN).update(
        status=PendingAction.Status.DONE, last_error="abandoned_by_stop", completed_at=Now(), updated_at=Now())
    AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="cancelled", signing_status="cancelled",
                                                            updated_at=Now())
    return "cancelled"


def cancel_agreement(instance_id: int, user) -> AgreementInstance:
    """Also the remedy for `cancel_uncertain` once its reconciliation has ended: the unknown cancel is set aside (a
    decision, never a known outcome) and a new cancel runs, which re-reads first and cancels only a pending envelope."""
    require(user, "manage_agreements")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application, instance = _lock(instance_id)
        if instance.issue_status == "cancel_uncertain":
            attempts = EnvelopeAttempt.objects.filter(instance=instance, step=EnvelopeAttempt.Step.CANCEL,
                                                      outcome=EnvelopeAttempt.Outcome.UNKNOWN)
            if PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref__in=[str(a.public_id) for a in attempts],
                                            status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists():
                raise Refused("reconciliation_in_progress")
            for attempt in attempts:
                for item in StaffItem.objects.filter(reason_code=handlers.CANCEL_UNKNOWN, status=StaffItem.Status.OPEN,
                                                     dedupe_key=f"cancel:{attempt.public_id}"):
                    resolve_item(item, code="decided_cancel_again", actor_ref=actor,
                                 effects={"instance": str(instance.public_id)})
            attempts.update(outcome=EnvelopeAttempt.Outcome.DECIDED_NOT_SENT, finished_at=Now())
            PendingAction.objects.filter(kind="cancel_agreement", input_ref=str(instance.public_id),
                                         status=PendingAction.Status.UNCERTAIN).update(
                status=PendingAction.Status.DONE, last_error="decided_cancel_again", completed_at=Now(), updated_at=Now())
            AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="failed_needs_staff", updated_at=Now())
            instance.refresh_from_db()
        elif instance.issue_status not in LIVE:
            raise Refused("not_live")
        done = _close(instance, actor)
        event(application, "agreement_cancel_requested", {"instance": str(instance.public_id), "result": done},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    instance.refresh_from_db()
    return instance


def reissue_agreement(instance_id: int, user) -> AgreementInstance:
    """P4-D-9: after a decline, expiry or cancellation, a decision-maker reissues as a new instance; the old one is
    marked superseded. An expired envelope is still open at the provider, so it is cancelled first."""
    from .completion import stopped

    require(user, "manage_agreements")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application, old = _lock(instance_id)
        if application.stage != Stage.AGREEMENTS or stopped(application):
            raise Refused("agreements_not_open")
        if old.issue_status == "superseded":
            raise Refused("already_superseded")
        if not (old.issue_status == "cancelled" or old.signing_status == "declined"):
            raise Refused("cancel_first")
        if StaffItem.objects.filter(application=application, status=StaffItem.Status.OPEN,
                                    reason_code="agreement_completed_after_cancel",
                                    dedupe_key__endswith=str(old.public_id)).exists():
            raise Refused("completion_after_cancel_open")  # the provider shows it signed: staff decide first
        _earlier_types_passed(application, old.agreement_type)
        version = handlers.approved_version(old.agreement_type.key)
        if version is None:
            raise Refused("no_approved_template")
        AgreementInstance.objects.filter(pk=old.pk).update(issue_status="superseded", updated_at=Now())
        try:
            new = handlers.start_agreement(application, version, actor)
        except ValueError as exc:
            raise Refused(str(exc)) from None
        event(application, "agreement_reissued", {"old": str(old.public_id), "new": str(new.public_id)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    return new


def stop_agreements(application_id: int, user, reason: str) -> list:
    """P4-D-20: withdrawal, closure or a hold during `agreements` cancels every live envelope and issues nothing more.
    The stage itself moves only through the POL-12 services (P5)."""
    require(user, "manage_agreements")
    if reason not in STOP_REASONS:
        raise Refused("unknown_reason")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        if application.stage != Stage.AGREEMENTS:
            raise Refused("not_in_agreements")
        if _final_stop(application) is not None:
            raise Refused("stopped_for_good")  # a withdrawal or closure is never turned into a resumable hold
        results = []
        live = list(AgreementInstance.objects.select_for_update(of=("self",))
                    .filter(application=application, issue_status__in=LIVE).order_by("id"))
        for instance in live:  # an exchange in flight gets a recorded cancel request instead of a refusal (D-42)
            if instance.signing_status == "signing_complete_verified":
                continue  # signed agreements stay signed
            results.append(_close(instance, actor))
        event(application, "agreements_stopped", {"reason": reason, "closed": len(results)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    return results


def decide_uncertain_distribute(instance_id: int, user, choice: str) -> AgreementInstance:
    """An unknown distribute that reconciliation could not settle: distribute again (the step re-reads first and only
    distributes a draft) or cancel. The attempt records the decision, never a known outcome."""
    require(user, "decide_uncertain_agreement")
    if choice == "cancel":
        require(user, "manage_agreements")  # cancelling is the manage permission's act, whoever decides (4B.2 review)
    if choice not in ("redistribute", "cancel"):
        raise Refused("unknown_choice")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application, instance = _lock(instance_id)
        if instance.issue_status != "distribute_uncertain":
            raise Refused("not_uncertain")
        attempt = EnvelopeAttempt.objects.filter(instance=instance, step=EnvelopeAttempt.Step.DISTRIBUTE,
                                                 outcome=EnvelopeAttempt.Outcome.UNKNOWN).order_by("-id").first()
        if attempt is None:
            raise Refused("no_unknown_attempt")
        if PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref=str(attempt.public_id),
                                        status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists():
            raise Refused("reconciliation_in_progress")
        EnvelopeAttempt.objects.filter(pk=attempt.pk).update(outcome=EnvelopeAttempt.Outcome.DECIDED_NOT_SENT,
                                                             finished_at=Now())
        PendingAction.objects.filter(kind=handlers.DISTRIBUTE, input_ref=str(instance.public_id),
                                     status=PendingAction.Status.UNCERTAIN).update(
            status=PendingAction.Status.DONE, last_error=f"decided_{choice}", completed_at=Now(), updated_at=Now())
        if choice == "redistribute":
            AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="distribute_pending", updated_at=Now())
            series = PendingAction.objects.filter(kind=handlers.DISTRIBUTE, input_ref=str(instance.public_id)).count()
            handlers.enqueue_distribute(instance, series)
        else:
            AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="failed_needs_staff", updated_at=Now())
            instance.refresh_from_db()
            _close(instance, actor)
        for item in StaffItem.objects.filter(reason_code=handlers.DISTRIBUTE_UNKNOWN,
                                             dedupe_key=f"distribute:{attempt.public_id}", status=StaffItem.Status.OPEN):
            resolve_item(item, code=f"decided_{choice}", actor_ref=actor, effects={"instance": str(instance.public_id)})
        event(application, "agreement_distribute_decided", {"instance": str(instance.public_id), "choice": choice},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    instance.refresh_from_db()
    return instance


def resume_agreements(application_id: int, user) -> None:
    """D-42: an explicit decision-maker act after a hold, once every cancellation has been reconciled. It reissues
    only the unfinished agreements still needed, each as a new instance and key; verified agreements and all history
    stay. It also re-runs the sequence after staff fixed what stopped it (a missing template, a contact to verify
    again). It never clears an automation pause, a delivery block or an agreement-integrity hold, and withdrawal and
    closure are not resumable here (POL-12, P5)."""
    from .completion import RESUMED_EVENT, STOPPED_EVENT, enqueue_advance, integrity_hold_open

    require(user, "manage_agreements")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        if application.stage != Stage.AGREEMENTS:
            raise Refused("not_in_agreements")
        if _final_stop(application) is not None:
            raise Refused("stopped_for_good")
        instances = list(AgreementInstance.objects.filter(application=application))
        if any(i.issue_status in ("cancel_pending", "cancel_uncertain") or _in_flight(i)
               or (i.cancel_requested_at and i.issue_status not in ("cancelled", "superseded")) for i in instances):
            raise Refused("cancellation_not_reconciled")  # resume only after every cancel has settled
        if any(integrity_hold_open(i) for i in instances):
            raise Refused("integrity_hold_open")  # resolved only through the integrity path (D-43)
        resumed = ApplicationEvent.objects.create(application=application, kind=RESUMED_EVENT, data={},
                                                  actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
        enqueue_advance(application, authorization=f"resume:{resumed.pk}")


# --- D-43: agreement integrity, and D-44: re-arming the orphan watch --------------------------------------------------

INTEGRITY_DISPOSITIONS = ("continue", "replace", "escalate")
REASON_MIN = 10


def integrity_state(instance) -> dict:
    """What the integrity screen shows and the services re-check: the open hold, the latest read, and a digest that
    ties a decision to exactly that state."""
    from .completion import INTEGRITY_HOLD
    from .models import ProviderObservation

    item = StaffItem.objects.filter(reason_code=INTEGRITY_HOLD, dedupe_key=f"integrity:{instance.public_id}",
                                    status=StaffItem.Status.OPEN).first()
    latest = (ProviderObservation.objects.filter(instance=instance, source=ProviderObservation.Source.READ)
              .order_by("-id").first())
    fresh = bool(item and latest and latest.observed_at > item.opened_at)
    matching = bool(fresh and latest.envelope_status == "COMPLETED" and latest.identity_match
                    and latest.recipients_match and latest.all_required_signed)
    basis = f"{instance.pk}:{item.pk if item else 0}:{latest.pk if latest else 0}"
    return {"item": item, "latest": latest, "fresh": fresh, "matching": matching,
            "digest": hashlib.sha256(basis.encode()).hexdigest()}


def recheck_integrity(instance_id: int, user) -> None:
    """A fresh read of the held agreement (the minimum interval still applies)."""
    from .completion import enqueue_read

    require(user, "resolve_agreement_integrity")
    with transaction.atomic():
        application, instance = _lock(instance_id)
        if integrity_state(instance)["item"] is None:
            raise Refused("no_integrity_hold")
        enqueue_read(instance)
        event(application, "agreement_integrity_recheck", {"instance": str(instance.public_id)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=f"user:{user.pk}")


def resolve_integrity(instance_id: int, user, disposition: str, reason: str, expected_digest: str) -> AgreementInstance:
    """D-43. `continue` needs a read recorded after the hold that shows the agreement complete, ours, with exactly our
    recipients and every required signature. `replace` keeps the verified history and makes a new generation the
    eligible one. `escalate` records that the case needs the owner or counsel and keeps everything blocked. The
    expected recipients are never changed to match the provider's, and no disposition claims to void an agreement."""
    require(user, "resolve_agreement_integrity")
    if disposition not in INTEGRITY_DISPOSITIONS:
        raise Refused("unknown_disposition")
    raw = (reason or "").strip()
    if len(raw) > 500:
        raise Refused("reason_too_long")  # refused, not cut: the record is what was written
    note = clean_note(raw)
    if len(note) < REASON_MIN:
        raise Refused("reason_needed")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application, instance = _lock(instance_id)
        state = integrity_state(instance)
        if state["item"] is None:
            raise Refused("no_integrity_hold")
        if expected_digest != state["digest"]:
            raise Refused("changed_since_shown")
        # The staff-written reason is kept once (security review): in the resolution note, or, for an escalation that
        # resolves nothing, in its event. Other events carry codes only.
        data = {"instance": str(instance.public_id), "disposition": disposition}
        if disposition == "escalate":
            event(application, "agreement_integrity_escalated", {**data, "reason": note},
                  actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
            return instance  # still held: a legal question is the owner's and counsel's
        if disposition == "continue":
            if not state["matching"]:
                raise Refused("no_fresh_matching_read")
            resolve_item(state["item"], code="continued_on_fresh_match", actor_ref=actor, note=note,
                         effects={"instance": str(instance.public_id), "observation": state["latest"].pk})
            event(application, "agreement_integrity_resolved", data, actor_type=ApplicationEvent.ActorType.STAFF,
                  actor_ref=actor)
            from .completion import enqueue_advance

            enqueue_advance(application)  # the sequence continues where the hold stopped it (QA review)
            instance.refresh_from_db()
            return instance
        _open_for_new_work(application)  # replace issues a new signing request: never after a stop or during a pause
        require(user, "manage_agreements")
        version = handlers.approved_version(instance.agreement_type.key)
        if version is None:
            raise Refused("no_approved_template")
        AgreementInstance.objects.filter(pk=instance.pk).update(replaced_at=Now(), replacement_reason="integrity_replaced",
                                                                updated_at=Now())
        try:
            new = handlers.start_agreement(application, version, actor)
        except ValueError as exc:
            raise Refused(str(exc)) from None
        resolve_item(state["item"], code="replaced_by_new_generation", actor_ref=actor, note=note,
                     effects={"instance": str(instance.public_id), "replacement": str(new.public_id)})
        event(application, "agreement_integrity_resolved", {**data, "replacement": str(new.public_id)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    return new


def rearm_orphan_watch(attempt_id: int, user) -> None:
    """D-44: after the bounded watch ended unresolved, a decision-maker may look again, a bounded number of times."""
    require(user, "manage_agreements")
    actor = f"user:{user.pk}"
    attempt = EnvelopeAttempt.objects.select_related("instance__application").get(pk=attempt_id)
    with transaction.atomic():
        application, _ = _lock(attempt.instance_id)
        attempt.refresh_from_db()
        if attempt.outcome not in (EnvelopeAttempt.Outcome.DECIDED_NOT_SENT, EnvelopeAttempt.Outcome.ABANDONED):
            raise Refused("not_watched")
        item = StaffItem.objects.filter(reason_code=handlers.ORPHAN_WATCH_ENDED, dedupe_key=f"watch:{attempt.public_id}",
                                        status=StaffItem.Status.OPEN).first()
        if item is None:
            raise Refused("watch_not_ended")
        rearms = application.events.filter(kind="agreement_orphan_watch_rearmed", data__attempt=str(attempt.public_id))
        if rearms.count() >= handlers.MAX_WATCH_REARMS:
            raise Refused("rearm_limit_reached")
        watches = PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref=str(attempt.public_id),
                                               idempotency_key__contains=":watch:").count()
        event(application, "agreement_orphan_watch_rearmed", {"attempt": str(attempt.public_id)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
        resolve_item(item, code="watch_rearmed", actor_ref=actor, effects={"attempt": str(attempt.public_id)})
        handlers.enqueue_reconcile(attempt, watches + 1, watch=True, grace=0)
