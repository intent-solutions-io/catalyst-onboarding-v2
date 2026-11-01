"""Reviewed ownership of an existing imported mailbox; never create or reactivate it."""

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models.functions import Now

from applications.models import Application, TERMINAL_STAGES
from correspondence.common import Refused
from correspondence.staff_items import clean_note, event
from provisioning import adapter, closure, core, services
from provisioning.models import ProvisioningEvidence, ProvisioningRequest
from workflow.models import PendingAction

from . import mailbox_history, review
from .models import ImportedRecord

CONFIRMED = "legacy_mailbox_ownership_confirmed"
RECONCILED = "legacy_mailbox_reconciled"


def reconciliation(request):
    return request.application.events.filter(
        kind=RECONCILED, data__request=str(request.public_id)
    ).first()


def transferred(request):
    if request.superseded_by_id is None:
        return False
    receipt = reconciliation(request)
    return receipt is not None and receipt.data.get("successor") == str(
        request.superseded_by.public_id
    )


def native_successor(request):
    return request.application.events.filter(
        kind=RECONCILED,
        data__successor=str(request.public_id),
        data__reservation=str(request.reservation.public_id),
    ).exists()


def settled_absent(request):
    receipt = reconciliation(request)
    return receipt is not None and receipt.data.get("decision") == "absent"


def imported_records(request):
    return ImportedRecord.objects.filter(
        application_id=request.application_id,
        v1_table="mailbox_account",
        target=f"provisioning.AddressReservation:{request.reservation.public_id}",
    )


def ownership_unreviewed(request):
    """Imported presence is not proof of ownership, nor proof that no mailbox exists."""
    return (
        imported_records(request).exists()
        and not (
            transferred(request) or native_successor(request) or settled_absent(request)
        )
        and not closure.proven_ours(request)
        and not closure.refused_as_foreign(request)
    )


def can_confirm(user):
    return services.can(user, "operate_provisioning") and user.has_perm(
        "applications.view_application"
    )


def _state(application, request_id, expected_digest):
    state = review.review_state(application)
    if state["digest"] != expected_digest:
        raise Refused("changed_since_shown")
    if state["pause"] is None and application.stage not in TERMINAL_STAGES:
        raise Refused("paused_or_closed_case_required")
    request = (
        ProvisioningRequest.objects.select_related("reservation")
        .filter(pk=request_id, application=application)
        .first()
    )
    if request is None or request.reservation.released_at is not None:
        raise Refused("imported_mailbox_required")
    records = list(imported_records(request))
    if len(records) != 1:
        raise Refused("imported_mailbox_required")
    record = records[0]
    snapshot = mailbox_history.settled(application, state["case"].v1_case_id)
    current = next(
        (a for a in snapshot.data["accounts"] if a["id"] == record.v1_id), None
    )
    if current is None or current["address_sha256"] != mailbox_history.address_digest(
        request.reservation.local_part, request.reservation.domain
    ):
        raise Refused("legacy_mailbox_identity_changed")
    if snapshot.data["case_state"] != state["case"].v1_state:
        raise Refused("legacy_mailbox_case_requires_reconciliation")
    if current.get("welcome_send_started_at") and not current.get("welcome_sent_at"):
        raise Refused("legacy_welcome_delivery_requires_reconciliation")
    if (
        record.data.get("case_id") != state["case"].v1_case_id
        or current.get("status") != "created"
        or not current.get("created_at_provider")
    ):
        raise Refused("legacy_mailbox_creation_requires_reconciliation")
    if request.status not in ("active", "stopped") or request.method != "checklist":
        raise Refused("legacy_mailbox_state_requires_reconciliation")
    if closure.refused_as_foreign(request):
        raise Refused("mailbox_previously_refused_as_foreign")
    if (
        request.attempts.filter(
            step="create", outcome__in=("sending", "unknown")
        ).exists()
        or request.setups.exists()
    ):
        raise Refused("native_mailbox_operation_requires_reconciliation")
    if (
        PendingAction.objects.filter(
            input_ref=str(request.public_id), status__in=("queued", "running", "held")
        ).exists()
        and not application.events.filter(
            kind=CONFIRMED, data__request=str(request.public_id)
        ).exists()
    ):
        raise Refused("native_mailbox_operation_in_flight")
    return state, request, record


def confirm(
    application_id,
    request_id,
    user,
    *,
    expected_digest,
    source_stopped,
    ownership_reviewed,
    note,
):
    if not can_confirm(user):
        raise PermissionDenied("legacy_mailbox_handover_authority_required")
    note = clean_note(note)
    if source_stopped is not True or ownership_reviewed is not True or len(note) < 10:
        raise Refused("reviewed_mailbox_handover_required")
    if connection.in_atomic_block:
        raise Refused("provider_read_requires_no_transaction")
    application = Application.objects.get(pk=application_id)
    state, request, record = _state(application, request_id, expected_digest)
    previous = application.events.filter(
        kind=CONFIRMED, data__request=str(request.public_id)
    ).first()
    if previous:
        return previous

    def identity(request):
        return (
            request.reservation_id,
            request.reservation.address,
            request.status,
            request.stop_requested_at,
            request.quota_mb,
            request.send_limit,
        )

    expected_identity = identity(request)
    mailbox = adapter.host().read(
        request.reservation.domain, request.reservation.local_part
    )
    if mailbox is None:
        raise Refused("legacy_mailbox_not_found")
    if (mailbox.domain.lower(), mailbox.local_part.lower()) != (
        request.reservation.domain.lower(),
        request.reservation.local_part.lower(),
    ):
        raise Refused("mailbox_identity_mismatch")
    # Suspended access must not be mistaken for an active account. The handover never unsuspends it.
    if state["case"].v1_state == "suspended" and not mailbox.suspended:
        raise Refused("legacy_suspension_requires_reconciliation")
    with transaction.atomic():
        application, _ = core.lock(application_id, request_id)
        state, request, record = _state(application, request_id, expected_digest)
        if identity(request) != expected_identity:
            raise Refused("mailbox_changed_during_read")
        previous = application.events.filter(
            kind=CONFIRMED, data__request=str(request.public_id)
        ).first()
        if previous:
            return previous
        evidence = ProvisioningEvidence.objects.create(
            request=request,
            kind=ProvisioningEvidence.Kind.STAFF_CONFIRMED,
            actor_ref=services.actor(user),
            note=note,
            facts={
                "decision": "ours",
                "source": "first_generation",
                "record": record.pk,
                **mailbox.facts(),
            },
        )
        stopped = (
            application.stage in TERMINAL_STAGES
            or request.stop_requested_at is not None
        )
        if stopped:
            if request.stop_requested_at is None:
                core.set_status(request, "stopped", stop_requested_at=Now())
                request.refresh_from_db()
            closure.ensure_revocations(request, services.actor(user))
        event(
            application,
            CONFIRMED,
            {
                "request": str(request.public_id),
                "record": record.pk,
                "evidence": evidence.pk,
                "source_sha256": state["sha256"],
                "mailbox_history": mailbox_history.latest(application).pk,
                "source_stopped_attested": True,
                "ownership_reviewed": True,
                "revocation_requested": stopped,
                "note": note,
            },
            actor_type="staff",
            actor_ref=services.actor(user),
        )
        return application.events.get(
            kind=CONFIRMED, data__request=str(request.public_id)
        )
