"""Prepare the missing native provisioning handoff for a reviewed v1 release-pending case."""

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction

from agreements import completion
from applications.models import Application, Stage
from correspondence.common import Refused
from correspondence.models import Question, StaffItem
from correspondence.staff_items import clean_note, event
from provisioning import auto_release, services
from workflow.models import PendingAction

from . import mailbox_history, mapping, review, signing_history

PREPARED = "legacy_release_handoff_prepared"


def can_prepare(user):
    return review.can_review(user) and services.can(user, "approve_provisioning")


def state(application):
    reviewed = review.review_state(application)
    refs, prerequisite_digest, reason = completion.prerequisites(application)
    return {
        "review": reviewed,
        "refs": refs,
        "prerequisite_digest": prerequisite_digest,
        "reason": reason,
        "digest": review.digest(
            {
                "review": reviewed["digest"],
                "refs": refs,
                "prerequisites": prerequisite_digest,
                "reason": reason,
            }
        ),
    }


def _validated(application, expected_digest):
    from assessments.decisions import IDENTITY_ITEMS
    from correspondence.staff_actions import PAUSE_CAUSES

    current = state(application)
    reviewed = current["review"]
    if current["digest"] != expected_digest:
        raise Refused("changed_since_shown")
    if (
        application.stage != Stage.AGREEMENTS_COMPLETE
        or reviewed["case"].v1_state != "release_pending"
    ):
        raise Refused("legacy_release_pending_case_required")
    previous = application.events.filter(kind=PREPARED).first()
    if reviewed["pause"] is None or (
        previous is None and not review.has_import_pause(reviewed)
    ):
        raise Refused("reviewed_import_pause_required")
    if not application.contact_verified_at or not reviewed["version"]:
        raise Refused("verified_contact_and_adopted_submission_required")
    records = reviewed["records"]
    if (
        any(r["v1_table"] in ("case_release", "mailbox_account") for r in records)
        or application.provisioning_requests.exists()
    ):
        raise Refused("legacy_provisioning_requires_reconciliation")
    provisioning = mailbox_history.settled(
        application, reviewed["case"].v1_case_id
    ).data
    if provisioning["case_state"] != "release_pending":
        raise Refused("later_legacy_state_requires_reconciliation")
    if provisioning["accounts"] or provisioning["releases"]:
        raise Refused("legacy_provisioning_requires_reconciliation")
    # The append-only original rows must not hide a later source transition or agreement change.
    agreements = [r for r in records if r["v1_table"] == "agreement"]
    if not agreements:
        raise Refused("frozen_agreement_history_required")
    for record in agreements:
        histories = [
            r
            for r in records
            if r["v1_table"] == signing_history.TABLE
            and r["data"].get("agreement_id") == record["v1_id"]
        ]
        if not histories:
            raise Refused("frozen_agreement_history_required")
        history = max(histories, key=lambda r: r["id"])["data"]
        if history.get("schema") != 1 or history.get("jobs_complete") is not True:
            raise Refused("frozen_agreement_history_required")
        if (
            history["case_state"] != "release_pending"
            or history["agreement"].get("status") not in mapping.COMPLETED_AGREEMENT
        ):
            raise Refused("later_legacy_state_requires_reconciliation")
        if any(
            j.get("case_id") != reviewed["case"].v1_case_id
            or j.get("outcome_unknown")
            or j["status"] not in ("queued", "succeeded", "failed", "cancelled")
            or (
                j["status"] == "queued"
                and (j["kind"] != "signing_reminder" or j["attempts"] != 0)
            )
            for j in history["jobs"]
        ):
            raise Refused("legacy_signing_delivery_requires_reconciliation")
    later = [
        r
        for r in records
        if r["v1_table"] == "case_event"
        and r["data"].get("subject") == "case"
        and r["data"].get("to_state")
        and str(r["run_ref"]) != str(reviewed["case"].run_ref)
    ]
    if (
        later
        and max(later, key=lambda r: (str(r["occurred_at"] or ""), r["id"]))["data"][
            "to_state"
        ]
        != "release_pending"
    ):
        raise Refused("later_legacy_state_requires_reconciliation")
    if current["reason"]:
        raise Refused(current["reason"])
    if (
        completion.stopped(application)
        or StaffItem.objects.filter(
            application=application,
            status="open",
            reason_code__in=(*IDENTITY_ITEMS, *PAUSE_CAUSES),
        ).exists()
    ):
        raise Refused("identity_or_safety_item_open")
    if application.inbound_messages.filter(
        status__in=("received", "awaiting_processing")
    ).exists():
        raise Refused("inbound_review_in_flight")
    if (
        Question.objects.filter(application=application)
        .exclude(status__in=("satisfied", "withdrawn"))
        .exists()
    ):
        raise Refused("native_question_pending")
    if previous:
        if previous.data["handover_digest"] != current["digest"]:
            raise Refused("existing_handoff_requires_reconciliation")
        return current, previous
    if PendingAction.objects.filter(
        subject_type="application",
        subject_id=application.public_ref,
        status__in=("queued", "running", "held"),
    ).exists():
        raise Refused("native_work_requires_reconciliation")
    if PendingAction.objects.filter(
        idempotency_key=f"provision:{application.public_ref}"
    ).exists():
        raise Refused("native_handoff_already_exists")
    return current, None


def prepare(
    application_id,
    user,
    *,
    expected_digest,
    source_stopped,
    completion_reviewed,
    effects_reviewed,
    note,
):
    if not can_prepare(user):
        raise PermissionDenied("legacy_release_handover_authority_required")
    note = clean_note(note)
    if (
        source_stopped is not True
        or completion_reviewed is not True
        or effects_reviewed is not True
        or len(note) < 10
    ):
        raise Refused("reviewed_release_handover_required")
    if connection.in_atomic_block:
        raise Refused("provider_read_requires_no_transaction")
    application = Application.objects.get(pk=application_id)
    current, previous = _validated(application, expected_digest)
    if previous:
        return previous
    # References remain references; native live instances retain their normal fresh-provider-read gate.
    problem = completion.fresh_read_problem(application)
    if problem:
        raise Refused(problem)
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        current, previous = _validated(application, expected_digest)
        if previous:
            return previous
        handoff = PendingAction.objects.create(
            kind=completion.HANDOFF,
            subject_type="application",
            subject_id=application.public_ref,
            input_ref=f"agreements:{current['prerequisite_digest']}",
            idempotency_key=f"provision:{application.public_ref}",
            status=PendingAction.Status.HELD,
        )
        auto_release.enqueue(application, handoff)
        event(
            application,
            PREPARED,
            {
                "handoff": handoff.pk,
                "handover_digest": current["digest"],
                "source_sha256": current["review"]["sha256"],
                "prerequisites": current["refs"],
                "prerequisite_digest": current["prerequisite_digest"],
                "source_stopped_attested": True,
                "completion_reviewed": True,
                "effects_reviewed": True,
                "note": note,
            },
            actor_type="staff",
            actor_ref=f"user:{user.pk}",
        )
        return application.events.get(kind=PREPARED)
