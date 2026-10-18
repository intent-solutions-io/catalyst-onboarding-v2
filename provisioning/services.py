"""P5 staff and owner services for 5B.1 (023 sections 5 and 11; D-47). Synthetic only.

- `release` (the owner-run `activate_provisioning` command, step 1): a fresh Documenso read outside any transaction,
  then, under the application lock, the database checks, a reservation and one `ProvisioningRequest` awaiting
  approval, and the stage `agreements_complete -> provisioning`.
- `reserve_exception`: a reviewed address for a name the rule cannot form (P5-D-1).
- `approve`: the exact address, limits, method and prerequisite digest the approver saw (P5-D-3).
- `record_checklist_creation` and `attest_checklist_verification`: the recorded checklist path, with a different named
  verifier (P5-D-5).
- `confirm_found_mailbox`: staff confirm, or refuse, a mailbox found by evidence after an unknown create (023 11.3).
- `supersede`: retire a live request after its prerequisites changed (023 11.11).
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Stage
from applications.stages import StageConflict, transition
from correspondence.models import StaffItem
from correspondence.staff_items import clean_note, resolve_item
from workflow.models import PendingAction

from . import core, naming
from .models import LIVE_REQUEST, AddressReservation, ProvisioningAttempt, ProvisioningEvidence, ProvisioningRequest

REASON_MIN = 10


class Refused(Exception):
    pass


def can(user, permission: str) -> bool:
    return (user is not None and user.is_authenticated and user.is_active and not user.is_superuser
            and user.has_perm(f"provisioning.{permission}"))


def require(user, permission: str) -> None:
    if not can(user, permission):
        raise PermissionDenied(permission)


def actor(user) -> str:
    return f"user:{user.pk}"


def _reason(text: str) -> str:
    note = clean_note(text or "")
    if len(note) < REASON_MIN:
        raise Refused("reason_needed")
    return note


def _resolve(request, reason_code: str, code: str, who: str, note: str = "") -> None:
    for open_one in StaffItem.objects.filter(reason_code=reason_code, dedupe_key=f"provisioning:{request.public_id}",
                                             status=StaffItem.Status.OPEN):
        resolve_item(open_one, code=code, actor_ref=who, note=note)


# --- release ----------------------------------------------------------------------------------------------------

def _free(local_part: str, domain: str) -> bool:
    return not naming.reserved(local_part) and not AddressReservation.objects.filter(
        local_part__iexact=local_part, domain__iexact=domain, released_at__isnull=True).exists()


def release(action_id: int, activation_version: int, approval_ref: str, dry_run: bool = False) -> str:
    """One held hand-off. Returns a reason code ("released" or why it stays held)."""
    from agreements.completion import fresh_read_problem, prerequisites
    from applications.models import Application

    action = PendingAction.objects.get(pk=action_id)
    application = Application.objects.filter(public_ref=action.subject_id).first()
    if application is None:
        return "application_not_found"
    problem = fresh_read_problem(application)  # B1: outside any transaction (023 11.4)
    if problem:
        return problem
    with transaction.atomic():
        application, _ = core.lock(application.pk)
        action = PendingAction.objects.select_for_update(of=("self",)).get(pk=action_id)
        if action.status != PendingAction.Status.HELD:
            return "not_held"
        if application.stage != Stage.AGREEMENTS_COMPLETE:
            return "stage_not_agreements_complete"
        if core.paused(application):
            return "paused"
        problem = core.database_problem(application)
        if problem:
            return problem
        _, digest, _ = prerequisites(application)
        if action.input_ref != f"agreements:{digest}":
            core.record(application, "provisioning_release_refused", {"reason": "prerequisites_changed"}, "owner_command")
            return "prerequisites_changed"
        domain = settings.CATALYST_PROVISIONING_DOMAIN
        reservation = AddressReservation.objects.filter(application=application, released_at__isnull=True).first()
        if reservation is None:
            base = naming.proposal(application.display_name)
            local = next((c for c in naming.candidates(base) if _free(c, domain)), None) if base else None
            if local is None:
                from correspondence.staff_items import open_item

                open_item(core.ITEM_NAME_REVIEW, f"naming:{application.public_ref}", application=application)
                return "name_needs_review"
            if dry_run:
                return "released"
            reservation = AddressReservation.objects.create(application=application, local_part=local, domain=domain,
                                                            basis=AddressReservation.Basis.NAMING_RULE)
        if dry_run:
            return "released"
        method = settings.CATALYST_PROVISIONING_METHOD
        quota, limit = settings.CATALYST_PROVISIONING_QUOTA_MB, settings.CATALYST_PROVISIONING_SEND_LIMIT
        request = ProvisioningRequest.objects.create(
            application=application, reservation=reservation, method=method, quota_mb=quota, send_limit=limit,
            prerequisite_digest=digest,
            approval_digest=core.approval_digest(reservation.address, quota, limit, method, digest))
        transition(application.pk, (Stage.AGREEMENTS_COMPLETE,), Stage.PROVISIONING, event_kind="provisioning_released",
                   data={"request": str(request.public_id), "activation_version": activation_version,
                         "approval_ref": approval_ref}, actor_ref="owner_command")
        PendingAction.objects.filter(pk=action.pk).update(status=PendingAction.Status.DONE, completed_at=Now(),
                                                          updated_at=Now(), last_error="released")
    return "released"


def reserve_exception(application_id: int, local_part: str, user, reason: str) -> AddressReservation:
    """P5-D-1: a reviewed address for a one-part, non-Latin or preferred professional name. Same rules: safe, not
    reserved, not anyone else's."""
    from applications.models import Application

    require(user, "approve_provisioning")
    note = _reason(reason)
    try:
        local = naming.check(local_part)
    except naming.NamingRefused as exc:
        raise Refused(str(exc)) from None
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        if application.stage != Stage.AGREEMENTS_COMPLETE:
            raise Refused("stage_not_agreements_complete")
        if AddressReservation.objects.filter(application=application, released_at__isnull=True).exists():
            raise Refused("already_reserved")
        domain = settings.CATALYST_PROVISIONING_DOMAIN
        if not _free(local, domain):
            raise Refused("address_taken")
        reservation = AddressReservation.objects.create(application=application, local_part=local, domain=domain,
                                                        basis=AddressReservation.Basis.REVIEWED_EXCEPTION,
                                                        reviewed_by=actor(user))
        for open_one in StaffItem.objects.filter(reason_code=core.ITEM_NAME_REVIEW,
                                                 dedupe_key=f"naming:{application.public_ref}", status="open"):
            resolve_item(open_one, code="reviewed_exception", actor_ref=actor(user), note=note)
        core.record(application, "provisioning_address_exception", {"reservation": str(reservation.public_id)},
                    actor(user), actor_type="staff")
    return reservation


# --- approval -----------------------------------------------------------------------------------------------------

def approve(request_id: int, user, expected_digest: str) -> ProvisioningRequest:
    require(user, "approve_provisioning")
    request = ProvisioningRequest.objects.get(pk=request_id)
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        if request.status != "awaiting_approval":
            raise Refused("not_awaiting_approval")
        if expected_digest != request.approval_digest:
            raise Refused("changed_since_shown")
        problem = core.database_problem(application, request)
        if problem:
            raise Refused(problem)
        core.set_status(request, "approved", approved_by=actor(user), approved_at=Now())
        if request.method == ProvisioningRequest.Method.API:
            core.enqueue(core.CREATE, request, f"{core.CREATE}:{request.public_id}:0")
        else:
            core.item(core.ITEM_CHECKLIST, request)
        core.record(application, "provisioning_approved", {"request": str(request.public_id), "method": request.method},
                    actor(user), actor_type="staff")
    return request


# --- the checklist path (P5-D-4 fallback, P5-D-5) ------------------------------------------------------------------

def record_checklist_creation(request_id: int, user, note: str) -> None:
    require(user, "operate_provisioning")
    text = _reason(note)
    request = ProvisioningRequest.objects.get(pk=request_id)
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        if request.method != ProvisioningRequest.Method.CHECKLIST or request.status != "approved":
            raise Refused("not_an_approved_checklist_request")
        problem = core.database_problem(application, request)
        if problem:
            raise Refused(problem)
        ProvisioningEvidence.objects.create(request=request, kind=ProvisioningEvidence.Kind.CHECKLIST_CREATED,
                                            actor_ref=actor(user), note=text,
                                            facts={"address": request.reservation.address, "quota_mb": request.quota_mb,
                                                   "send_limit": request.send_limit})
        core.set_status(request, "created")
        core.record(application, "provisioning_checklist_created", {"request": str(request.public_id)}, actor(user),
                    actor_type="staff")


def attest_checklist_verification(request_id: int, user, note: str) -> None:
    """A different named staff member than the creator confirms the panel listing (P5-D-5). The database refuses the
    creator too."""
    require(user, "operate_provisioning")
    text = _reason(note)
    request = ProvisioningRequest.objects.get(pk=request_id)
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        if request.method != ProvisioningRequest.Method.CHECKLIST or request.status != "created":
            raise Refused("not_a_created_checklist_request")
        created = request.evidence.filter(kind=ProvisioningEvidence.Kind.CHECKLIST_CREATED).first()
        if created is None or created.actor_ref == actor(user):
            raise Refused("verifier_must_differ_from_creator")
        ProvisioningEvidence.objects.create(request=request, kind=ProvisioningEvidence.Kind.CHECKLIST_ATTESTED,
                                            actor_ref=actor(user), note=text)
        core.set_status(request, "verified")
        _resolve(request, core.ITEM_CHECKLIST, "verified", actor(user))
        core.record(application, "provisioning_verified", {"request": str(request.public_id), "by": "checklist"},
                    actor(user), actor_type="staff")


# --- found by evidence, conflicts and supersession -----------------------------------------------------------------

def confirm_found_mailbox(request_id: int, user, decision: str, reason: str) -> None:
    """023 11.3: after an unknown create, a mailbox read as present is ours only when staff confirm it."""
    require(user, "operate_provisioning")
    note = _reason(reason)
    if decision not in ("ours", "conflict"):
        raise Refused("unknown_decision")
    request = ProvisioningRequest.objects.get(pk=request_id)
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        if request.status != "found_by_evidence":
            raise Refused("not_found_by_evidence")
        ProvisioningEvidence.objects.create(request=request, kind=ProvisioningEvidence.Kind.STAFF_CONFIRMED,
                                            actor_ref=actor(user), note=note, facts={"decision": decision})
        if decision == "ours":
            core.set_status(request, "created")
            core.enqueue(core.VERIFY, request, f"{core.VERIFY}:{request.public_id}:0",
                         due_in=timedelta(seconds=settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS))
        else:
            core.set_status(request, "conflict")
        _resolve(request, core.ITEM_CONFIRM_FOUND, decision, actor(user), note)
        core.record(application, "provisioning_found_decided", {"request": str(request.public_id), "decision": decision},
                    actor(user), actor_type="staff")


MAILBOX_MAY_EXIST = (ProvisioningAttempt.Outcome.SUCCEEDED, ProvisioningAttempt.Outcome.UNKNOWN,
                     ProvisioningAttempt.Outcome.FOUND_BY_EVIDENCE, ProvisioningAttempt.Outcome.SENDING)


def supersede(request_id: int, user, reason: str) -> None:
    """023 11.11: retire a live request (its prerequisites changed, or a conflict needs a new address). The
    reservation stays held, and a bounded watch runs, while a mailbox may exist for it; otherwise it is released.
    With no live request left the stage returns to `agreements_complete`, and a new held hand-off awaits release and
    a new approval."""
    from agreements.completion import prerequisites

    require(user, "operate_provisioning")
    note = _reason(reason)
    request = ProvisioningRequest.objects.get(pk=request_id)
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        if request.status in ("active", "superseded", "stopped", "recovered_after_stop"):
            raise Refused("request_closed")
        if request.status in ("create_pending", "create_uncertain"):
            raise Refused("create_in_flight")  # reconcile first; never retire under an exchange
        may_exist = request.attempts.filter(step="create", outcome__in=MAILBOX_MAY_EXIST).exists() or \
            request.status in ("found_by_evidence", "created", "verify_uncertain", "verified")
        core.set_status(request, "superseded")
        if may_exist:
            core.enqueue(core.RECONCILE, request, f"{core.RECONCILE}:{request.public_id}:watch:0",
                         due_in=timedelta(seconds=settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS))
        else:
            AddressReservation.objects.filter(pk=request.reservation_id, released_at__isnull=True).update(
                released_at=Now(), released_by=actor(user))
        for code in (core.ITEM_CONFLICT, core.ITEM_FAILED, core.ITEM_BLOCKED, core.ITEM_CHECKLIST):
            _resolve(request, code, "superseded", actor(user), note)
        if not ProvisioningRequest.objects.filter(application=application,
                                                  status__in=LIVE_REQUEST).exists():
            try:
                transition(application.pk, (Stage.PROVISIONING,), Stage.AGREEMENTS_COMPLETE,
                           event_kind="provisioning_superseded", data={"request": str(request.public_id)},
                           actor_type="staff", actor_ref=actor(user))
            except StageConflict:
                pass
            _, digest, _ = prerequisites(application)
            n = PendingAction.objects.filter(kind=core.HANDOFF, subject_id=application.public_ref).count()
            PendingAction.objects.create(kind=core.HANDOFF, subject_type="application", subject_id=application.public_ref,
                                         input_ref=f"agreements:{digest}",
                                         idempotency_key=f"{core.HANDOFF}:{application.public_ref}:{n}",
                                         status=PendingAction.Status.HELD)
