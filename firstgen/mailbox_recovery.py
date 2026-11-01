"""Explicit dispositions of frozen v1 mailbox effects; no provider write in the handover."""

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models.functions import Now

from agreements import completion
from applications.models import Application, Stage, TERMINAL_STAGES
from applications.stages import transition
from correspondence.common import Refused
from correspondence.messages import verified_address
from correspondence.models import StaffItem
from correspondence.staff_items import event
from provisioning import adapter, closure, core, services
from provisioning.models import ProvisioningEvidence, ProvisioningRequest
from workflow.models import PendingAction

from . import mailbox_history, mailboxes, mapping, review, signing_history

RECONCILED = "legacy_mailbox_reconciled"
DECISIONS = ("absent", "recover_credentials", "received", "foreign", "protect_owned")


def can_reconcile(user):
    return mailboxes.can_confirm(user) and services.can(user, "approve_provisioning")


def state(application, request):
    reviewed = review.review_state(application)
    refs, prerequisite, problem = completion.prerequisites(application)
    identity = [
        request.pk,
        request.status,
        request.reservation_id,
        request.reservation.address,
        request.reservation.released_at,
        request.stop_requested_at,
        request.superseded_by_id,
    ]
    digest = review.digest(
        {
            "review": reviewed["digest"],
            "request": identity,
            "prerequisites": prerequisite,
            "problem": problem,
        }
    )
    return {
        "review": reviewed,
        "refs": refs,
        "prerequisite": prerequisite,
        "problem": problem,
        "digest": digest,
    }


def _validated(application, request, expected_digest, decision, quota, limit):
    from assessments.decisions import IDENTITY_ITEMS
    from correspondence.staff_actions import PAUSE_CAUSES

    current = state(application, request)
    reviewed = current["review"]
    previous = application.events.filter(
        kind=RECONCILED, data__request=str(request.public_id)
    ).first()
    if previous:
        if (
            expected_digest not in (previous.data["handover_digest"], current["digest"])
            or previous.data["source_sha256"] != reviewed["sha256"]
            or previous.data["decision"] != decision
            or previous.data["limits"] != [quota, limit]
        ):
            raise Refused("changed_since_shown")
        return current, None, None, previous
    if current["digest"] != expected_digest:
        raise Refused("changed_since_shown")
    stopped = (
        application.stage in TERMINAL_STAGES or request.stop_requested_at is not None
    )
    if not stopped and reviewed["pause"] is None:
        raise Refused("paused_or_closed_case_required")
    if (
        request.application_id != application.pk
        or request.method != "checklist"
        or not request.approved_by.startswith("first-generation:")
        or request.status not in ("active", "failed_needs_staff", "stopped")
        or request.reservation.released_at is not None
        or request.superseded_by_id
    ):
        raise Refused("original_imported_mailbox_required")
    records = list(mailboxes.imported_records(request))
    if len(records) != 1:
        raise Refused("original_imported_mailbox_required")
    snapshot = mailbox_history.current(application, reviewed["case"].v1_case_id)
    account = next(
        (a for a in snapshot.data["accounts"] if a["id"] == records[0].v1_id), None
    )
    if account is None or account["address_sha256"] != mailbox_history.address_digest(
        request.reservation.local_part, request.reservation.domain
    ):
        raise Refused("legacy_mailbox_identity_changed")
    if account["status"] not in ("approved", "created"):
        raise Refused("legacy_mailbox_state_requires_reconciliation")
    if any(
        j["status"]
        not in ("queued", "succeeded", "failed", "cancelled", "needs_reconcile")
        for j in snapshot.data["jobs"]
    ):
        raise Refused("source_job_still_in_flight")
    if request.attempts.exists() or request.setups.exists():
        raise Refused("native_mailbox_operation_requires_reconciliation")
    actions = PendingAction.objects.filter(
        subject_id=application.public_ref, status__in=("queued", "running", "held")
    )
    if stopped:
        actions = actions.exclude(kind=closure.REVOKE)
    if actions.exists():
        raise Refused("native_mailbox_operation_in_flight")
    if stopped:
        if decision not in ("absent", "foreign", "protect_owned"):
            raise Refused("stopped_case_requires_protection")
    else:
        if application.stage not in (Stage.PROVISIONING, Stage.ACTIVE) or snapshot.data[
            "case_state"
        ] not in ("provisioning", "active"):
            raise Refused("legacy_provisioning_case_required")
        if decision == "protect_owned":
            raise Refused("case_must_be_stopped_first")
        releases = snapshot.data["releases"]
        if len(releases) != 1 or not releases[0]["verified_at"]:
            raise Refused("verified_source_release_required")
        for agreement_id in (
            releases[0]["nda_agreement_id"],
            releases[0]["ua_agreement_id"],
        ):
            histories = [
                r
                for r in reviewed["records"]
                if r["v1_table"] == signing_history.TABLE
                and r["data"].get("agreement_id") == agreement_id
            ]
            history = max(histories, key=lambda r: r["id"])["data"] if histories else {}
            if (
                not history.get("jobs_complete")
                or history.get("agreement", {}).get("status")
                not in mapping.COMPLETED_AGREEMENT
                or any(
                    j.get("outcome_unknown")
                    or j.get("case_id") != reviewed["case"].v1_case_id
                    or j["status"] not in ("queued", "succeeded", "failed", "cancelled")
                    or (j["status"] == "queued" and j["attempts"] != 0)
                    for j in history.get("jobs", [])
                )
            ):
                raise Refused("current_source_agreement_completion_required")
        if (
            current["problem"]
            or completion.stopped(application)
            or not verified_address(application)
        ):
            raise Refused(
                current["problem"] or "current_agreement_and_contact_evidence_required"
            )
        if StaffItem.objects.filter(
            application=application,
            status="open",
            reason_code__in=(*IDENTITY_ITEMS, *PAUSE_CAUSES),
        ).exists():
            raise Refused("unresolved_identity_or_safety_item")
        if application.inbound_messages.filter(
            status__in=("received", "awaiting_processing")
        ).exists():
            raise Refused("unprocessed_correspondence")
        if decision == "absent" and any(
            r.data.get("status") == "created" or r.data.get("welcome_sent_at")
            for r in records
        ):
            raise Refused("previously_created_mailbox_cannot_be_recreated")
        if decision == "absent" and (
            account["status"] != "approved"
            or account["created_at_provider"]
            or account["welcome_send_started_at"]
            or account["welcome_sent_at"]
        ):
            raise Refused("previously_created_mailbox_cannot_be_recreated")
        if decision == "received" and (
            snapshot.data["case_state"] != "active"
            or account["status"] != "created"
            or not (account["welcome_send_started_at"] or account["welcome_sent_at"])
        ):
            raise Refused("source_welcome_evidence_required")
    current["stopped"] = stopped
    return current, snapshot, account, None


def reconcile(
    application_id,
    request_id,
    user,
    *,
    expected_digest,
    decision,
    quota_mb,
    send_limit,
    source_stopped,
    inflight_settled,
    ownership_reviewed,
    delivery_reviewed,
    note,
):
    if not can_reconcile(user):
        raise PermissionDenied("legacy_mailbox_reconciliation_authority_required")
    try:
        note = services._reason(note)
    except services.Refused as exc:
        raise Refused(str(exc)) from None
    if (
        decision not in DECISIONS
        or source_stopped is not True
        or inflight_settled is not True
        or ownership_reviewed is not True
        or delivery_reviewed is not True
    ):
        raise Refused("reviewed_mailbox_reconciliation_required")
    if (
        type(quota_mb) is not int
        or type(send_limit) is not int
        or quota_mb < 1
        or not 1 <= send_limit <= 9600
    ):
        raise Refused("invalid_mailbox_limits")
    if connection.in_atomic_block:
        raise Refused("provider_read_requires_no_transaction")
    application = Application.objects.get(pk=application_id)
    request = (
        ProvisioningRequest.objects.select_related("reservation")
        .filter(pk=request_id, application=application)
        .first()
    )
    if request is None:
        raise Refused("original_imported_mailbox_required")
    current, snapshot, account, previous = _validated(
        application, request, expected_digest, decision, quota_mb, send_limit
    )
    if previous:
        return previous
    if not current["stopped"]:
        problem = completion.fresh_read_problem(application)
        if problem:
            raise Refused(problem)
    found = adapter.host().read(
        request.reservation.domain, request.reservation.local_part
    )
    if found is not None and (found.domain.lower(), found.local_part.lower()) != (
        request.reservation.domain.lower(),
        request.reservation.local_part.lower(),
    ):
        raise Refused("mailbox_identity_mismatch")
    if (decision == "absent") != (found is None):
        raise Refused("mailbox_presence_does_not_match_decision")
    if decision in ("recover_credentials", "received", "protect_owned"):
        if not (account["created_at_provider"] or account["create_requested_at"]):
            raise Refused("source_never_requested_mailbox_creation")
        if closure.refused_as_foreign(request):
            raise Refused("mailbox_previously_refused_as_foreign")
        if not current["stopped"] and (
            found.suspended
            or (found.quota_mb, found.send_limit) != (quota_mb, send_limit)
        ):
            raise Refused("provider_limits_or_suspension_mismatch")
    with transaction.atomic():
        application, request = core.lock(application_id, request_id)
        current, snapshot, account, previous = _validated(
            application, request, expected_digest, decision, quota_mb, send_limit
        )
        if previous:
            return previous
        who = services.actor(user)
        facts = {
            "source": "first_generation",
            "mailbox_history": snapshot.pk,
            "present": found is not None,
            **(found.facts() if found is not None else {}),
        }
        ProvisioningEvidence.objects.create(
            request=request, kind="adapter_read", actor_ref=who, facts=facts
        )
        successor = None
        if decision in ("recover_credentials", "received", "protect_owned", "foreign"):
            ProvisioningEvidence.objects.create(
                request=request,
                kind="staff_confirmed",
                actor_ref=who,
                note=note,
                facts={
                    **facts,
                    "decision": "conflict" if decision == "foreign" else "ours",
                },
            )
        if not current["stopped"] and decision in ("absent", "recover_credentials"):
            # Preserve immutable source approval. A new request has current native prerequisites.
            core.set_status(request, "superseded")
            successor = ProvisioningRequest.objects.create(
                application=application,
                reservation=request.reservation,
                method="api",
                quota_mb=quota_mb,
                send_limit=send_limit,
                prerequisite_digest=current["prerequisite"],
                approval_digest=core.approval_digest(
                    request.reservation.address,
                    quota_mb,
                    send_limit,
                    "api",
                    current["prerequisite"],
                ),
                status="awaiting_approval" if decision == "absent" else "created",
                approved_by="" if decision == "absent" else who,
                approved_at=None if decision == "absent" else Now(),
            )
            core.set_status(request, "superseded", superseded_by=successor)
            if decision == "recover_credentials":
                ProvisioningEvidence.objects.create(
                    request=successor,
                    kind="staff_confirmed",
                    actor_ref=who,
                    note=note,
                    facts={
                        **facts,
                        "decision": "ours",
                        "predecessor": str(request.public_id),
                    },
                )
                core.enqueue(
                    core.VERIFY, successor, f"{core.VERIFY}:{successor.public_id}:0"
                )
            if application.stage == Stage.ACTIVE:
                application = transition(
                    application.pk,
                    (Stage.ACTIVE,),
                    Stage.PROVISIONING,
                    event_kind="legacy_credential_recovery_started",
                    actor_type="staff",
                    actor_ref=who,
                )
        elif decision == "received":
            core.set_status(request, "active")
            if application.stage == Stage.PROVISIONING:
                application = transition(
                    application.pk,
                    (Stage.PROVISIONING,),
                    Stage.ACTIVE,
                    event_kind="legacy_completed_access_adopted",
                    actor_type="staff",
                    actor_ref=who,
                    data={
                        "mailbox_history": snapshot.pk,
                        "delivery": "staff_verified_existing_receipt",
                    },
                )
        elif decision == "foreign":
            core.set_status(request, "conflict")
        if current["stopped"]:
            core.set_status(
                request,
                "stopped",
                **(
                    {"stop_requested_at": Now()}
                    if request.stop_requested_at is None
                    else {}
                ),
            )
        event(
            application,
            RECONCILED,
            {
                "request": str(request.public_id),
                "successor": str(successor.public_id) if successor else "",
                "reservation": str(request.reservation.public_id),
                "decision": decision,
                "mailbox_history": snapshot.pk,
                "source_sha256": current["review"]["sha256"],
                "handover_digest": expected_digest,
                "prerequisites": current["refs"],
                "limits": [quota_mb, send_limit],
                "source_stopped_attested": True,
                "inflight_settled_attested": True,
                "ownership_reviewed": True,
                "delivery_reviewed": True,
                "note": note,
            },
            actor_type="staff",
            actor_ref=who,
        )
        if current["stopped"]:
            closure.ensure_revocations(request, who)
        elif decision == "foreign":
            if application.stage == Stage.ACTIVE:
                application = transition(
                    application.pk,
                    (Stage.ACTIVE,),
                    Stage.PROVISIONING,
                    event_kind="legacy_mailbox_conflict_reviewed",
                    actor_type="staff",
                    actor_ref=who,
                )
            core.return_stage_if_idle(application, who)
        return application.events.get(
            kind=RECONCILED, data__request=str(request.public_id)
        )
