"""Staff services for P4 agreements (021 sections 5 and 9; 4B.1). One transaction each, the application locked first.

- `approve_template_version`: the owner approves one template version (POL-07; P4-D-1). Approving twice does nothing
  more; an approved version is never edited (database trigger).
- `decide_uncertain_create`: a decision-maker decides an unknown create that reconciliation could not settle
  (P4-D-8): mark it not sent and allow one new create under a **new** key, or abandon the agreement. The old key stays
  watched, so a late envelope is caught as an orphan and never verified (P4-D-19). A decision never rewrites the
  unknown outcome into a known one: the attempt records `decided_not_sent` or `abandoned`.

The permissions are assigned to no group by migration (021 section 9): they are granted to named people.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent, Stage
from correspondence.models import StaffItem
from correspondence.staff_items import event, resolve_item
from workflow.models import PendingAction

from . import handlers
from .models import AgreementInstance, AgreementTemplateVersion, EnvelopeAttempt

CHOICES = ("not_sent", "abandon")


class Refused(Exception):
    """A service refused; the message is a reason code."""


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


def _close(instance, actor) -> str:
    """Inside the caller's transaction. An instance with an envelope is cancelled at the provider (P4-D-18); one
    without is closed here, and an unknown create is set aside with its key watched, so a late envelope is cancelled
    as an orphan (P4-D-19). Returns what was done."""
    from .completion import enqueue_cancel_instance

    if instance.signing_status == "signing_complete_verified":
        raise Refused("agreement_already_signed")  # a signed agreement is never cancelled here
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


def _in_flight(instance) -> bool:
    return PendingAction.objects.filter(kind__in=(handlers.CREATE, handlers.DISTRIBUTE, "cancel_agreement"),
                                        input_ref=str(instance.public_id), status=PendingAction.Status.RUNNING).exists()


def cancel_agreement(instance_id: int, user) -> AgreementInstance:
    """Also the remedy for `cancel_uncertain` once its reconciliation has ended: the unknown cancel is set aside (a
    decision, never a known outcome) and a new cancel runs, which re-reads first and cancels only a pending envelope."""
    require(user, "manage_agreements")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application, instance = _lock(instance_id)
        if _in_flight(instance):
            raise Refused("provider_step_in_progress")  # decide once the running exchange has been recorded
        if instance.issue_status == "cancel_uncertain":
            attempts = EnvelopeAttempt.objects.filter(instance=instance, step=EnvelopeAttempt.Step.CANCEL,
                                                      outcome=EnvelopeAttempt.Outcome.UNKNOWN)
            if PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref__in=[str(a.public_id) for a in attempts],
                                            status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists():
                raise Refused("reconciliation_in_progress")
            attempts.update(outcome=EnvelopeAttempt.Outcome.DECIDED_NOT_SENT, finished_at=Now())
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
        results = []
        live = list(AgreementInstance.objects.select_for_update(of=("self",))
                    .filter(application=application, issue_status__in=LIVE).order_by("id"))
        if any(_in_flight(instance) for instance in live):
            raise Refused("provider_step_in_progress")  # a running create or distribute is recorded first (4B.2 review)
        for instance in live:
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
    """Resume after a hold (P4-D-20), or re-run the sequence after staff fixed what stopped it (a missing template, a
    contact to verify again, a refused gate read). Withdrawal and closure are final."""
    from .completion import RESUMED_EVENT, STOPPED_EVENT, enqueue_advance

    require(user, "manage_agreements")
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        if application.stage != Stage.AGREEMENTS:
            raise Refused("not_in_agreements")
        last = application.events.filter(kind__in=(STOPPED_EVENT, RESUMED_EVENT)).order_by("-id").first()
        if last is not None and last.kind == STOPPED_EVENT:
            if (last.data or {}).get("reason") != "on_hold":
                raise Refused("stopped_for_good")
            event(application, RESUMED_EVENT, {}, actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
        enqueue_advance(application)

