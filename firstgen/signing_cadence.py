"""Explicit transfer of an adopted envelope's remaining reminder or lapse timer."""

from datetime import datetime

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction

from agreements import provider, signing_reminder
from agreements.models import AgreementInstance
from applications.models import Application
from correspondence import scheduling
from correspondence.common import Refused
from correspondence.messages import verified_address
from correspondence.models import StaffItem
from correspondence.staff_items import clean_note, event
from workflow import business_days
from workflow.models import PendingAction

from . import agreements as adoption, review, signing_history

PREPARED = "legacy_signing_timers_prepared"


def instant(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result
    except ValueError, TypeError:
        raise Refused("legacy_delivery_time_missing") from None


def plan(state, record, envelope):
    histories = [
        r
        for r in state["records"]
        if r["v1_table"] == signing_history.TABLE
        and r["data"].get("agreement_id") == record.v1_id
    ]
    if not histories:
        raise Refused("signing_history_import_required")
    history = max(histories, key=lambda r: r["id"])
    data = history["data"]
    if data.get("schema") != 1 or data.get("jobs_complete") is not True:
        raise Refused("signing_job_history_incomplete")
    source = data["agreement"]
    if (
        source["provider_ref"] != envelope.id
        or source["external_ref"] != envelope.external_id
    ):
        raise Refused("legacy_envelope_identity_changed")
    if data["case_state"] not in ("nda_pending", "setup_pending", "lapsed"):
        raise Refused("later_legacy_state_requires_reconciliation")
    jobs = data["jobs"]
    for job in jobs:
        if job["case_id"] != state["case"].v1_case_id:
            raise Refused("legacy_signing_job_case_mismatch")
        if (
            job.get("outcome_unknown")
            or job["status"] not in ("queued", "succeeded", "failed", "cancelled")
            or (
                job["status"] == "queued"
                and (job["kind"] != "signing_reminder" or job["attempts"] != 0)
            )
        ):
            raise Refused("legacy_signing_delivery_requires_reconciliation")
        if job["kind"] == "signing_link_send" and job.get("applicant_round") is None:
            raise Refused("legacy_signing_round_unknown")
    reminders = [
        r
        for r in state["records"]
        if r["v1_table"] == "case_event"
        and r["data"].get("agreement_id") == record.v1_id
        and r["data"].get("event") == "signing_reminder_sent"
    ]
    succeeded = [j for j in jobs if j["status"] == "succeeded"]
    if sum(j["kind"] == "signing_reminder" for j in succeeded) > len(reminders):
        raise Refused("legacy_reminder_receipt_missing")
    spent = len(reminders) + sum(
        j["kind"] == "signing_link_send" and j["applicant_round"] > 1 for j in succeeded
    )
    anchor = max(
        [instant(source["status_changed_at"])]
        + [instant(j["completed_at"]) for j in succeeded]
        + [r["occurred_at"] for r in reminders]
    )
    result = {
        "history": history["id"],
        "delivered_followups": spent,
        "quiet_since": anchor.isoformat(),
        "kind": "",
        "due_at": "",
        "number": spent + 1,
    }
    if data["case_state"] == "lapsed":
        return result | {"reason": "already_lapsed_in_v1"}
    applicant = verified_address(state["case"].application)
    applicant_rows = [r for r in envelope.recipients if r.email.lower() == applicant]
    if any(r.expired or r.signing_status == "REJECTED" for r in applicant_rows):
        raise Refused("applicant_signing_state_requires_reconciliation")
    if envelope.status == "COMPLETED" or any(
        r.signing_status == "SIGNED" for r in applicant_rows
    ):
        return result | {"reason": "applicant_already_signed"}
    if source["status"] == "prepared" and envelope.status == "DRAFT":
        return result | {"reason": "native_distribution_will_schedule"}
    if source["status"] != "sent" or envelope.status != "PENDING":
        raise Refused("legacy_signing_state_requires_reconciliation")
    if (
        settings.CATALYST_SIGNING_REMINDER_MAX < 1
        or settings.CATALYST_SIGNING_REMINDER_BUSINESS_DAYS < 1
    ):
        raise Refused("signing_reminders_not_enabled")
    if spent < settings.CATALYST_SIGNING_REMINDER_MAX:
        return result | {
            "kind": scheduling.REMIND_SIGNING,
            "reason": "remaining_reminder",
            "due_at": business_days.after(
                anchor, settings.CATALYST_SIGNING_REMINDER_BUSINESS_DAYS
            ).isoformat(),
        }
    # A reply or revised application already recorded by v1 prevents a second closing note.
    if any(
        r["occurred_at"]
        and r["occurred_at"] > anchor
        and (
            r["v1_table"] == "intake_revision"
            or (
                r["v1_table"] == "applicant_message"
                and r["data"].get("direction") == "in"
            )
            or (
                r["v1_table"] == "case_event"
                and r["data"].get("from_state") == "lapsed"
            )
        )
        for r in state["records"]
    ):
        return result | {"reason": "applicant_returned_after_reminder"}
    if settings.CATALYST_LAPSE_AFTER_BUSINESS_DAYS < 1:
        raise Refused("lapse_not_enabled")
    return result | {
        "kind": scheduling.LAPSE,
        "reason": "reminder_budget_already_spent",
        "due_at": business_days.after(
            anchor, settings.CATALYST_LAPSE_AFTER_BUSINESS_DAYS
        ).isoformat(),
    }


def _state(application, instance_id, expected_digest):
    from assessments.decisions import IDENTITY_ITEMS
    from correspondence.staff_actions import PAUSE_CAUSES

    state = review.review_state(application)
    if state["digest"] != expected_digest:
        raise Refused("changed_since_shown")
    if state["pause"] is None or application.stage != "agreements":
        raise Refused("paused_signing_case_required")
    if StaffItem.objects.filter(
        application=application,
        status="open",
        reason_code__in=(*IDENTITY_ITEMS, *PAUSE_CAUSES),
    ).exists():
        raise Refused("identity_or_safety_item_open")
    if application.inbound_messages.filter(
        status__in=("received", "awaiting_processing")
    ).exists():
        raise Refused("inbound_review_in_flight")
    instance = (
        AgreementInstance.objects.select_related("template_version")
        .filter(pk=instance_id, application=application, replaced_at__isnull=True)
        .first()
    )
    receipt = application.events.filter(
        kind=adoption.ADOPTED,
        data__instance=str(instance.public_id) if instance else "",
    ).first()
    if (
        instance is None
        or receipt is None
        or instance.template_version.status != "approved"
    ):
        raise Refused("adopted_envelope_required")
    record = application.first_generation_records.get(pk=receipt.data["record"])
    return state, instance, record


def prepare(
    application_id,
    instance_id,
    user,
    *,
    expected_digest,
    source_stopped,
    timers_reviewed,
    note,
):
    if not adoption.can_adopt(user):
        raise PermissionDenied("legacy_envelope_handover_authority_required")
    note = clean_note(note)
    if source_stopped is not True or timers_reviewed is not True or len(note) < 10:
        raise Refused("reviewed_timer_handover_required")
    if connection.in_atomic_block:
        raise Refused("provider_read_requires_no_transaction")
    application = Application.objects.get(pk=application_id)
    state, instance, record = _state(application, instance_id, expected_digest)

    def identity(instance):
        return (
            instance.envelope_id,
            instance.external_key,
            instance.template_version_id,
            tuple(
                sorted(
                    instance.recipients.values_list("email", "role", "signing_order")
                )
            ),
        )

    expected_identity = identity(instance)
    previous = application.events.filter(
        kind=PREPARED, data__instance=str(instance.public_id)
    ).first()
    if previous:
        if previous.data["source_sha256"] != state["sha256"]:
            raise Refused("existing_timer_requires_reconciliation")
        return previous
    envelope = provider.read(instance.envelope_id)
    ours = sorted(
        (email.lower(), role, order)
        for email, role, order in instance.recipients.values_list(
            "email", "role", "signing_order"
        )
    )
    theirs = sorted(
        (r.email.lower(), r.role, r.signing_order) for r in envelope.recipients
    )
    if (
        envelope.id != instance.envelope_id
        or envelope.external_id != instance.external_key
        or envelope.template_number
        != instance.template_version.provider_template_number
        or envelope.type != "DOCUMENT"
        or ours != theirs
        or not instance.recipients.filter(
            who="applicant", email=verified_address(application)
        ).exists()
    ):
        raise Refused("provider_identity_or_recipients_mismatch")
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        state, instance, record = _state(application, instance_id, expected_digest)
        if identity(instance) != expected_identity:
            raise Refused("envelope_changed_during_read")
        previous = application.events.filter(
            kind=PREPARED, data__instance=str(instance.public_id)
        ).first()
        if previous:
            return previous
        proposed = plan(state, record, envelope)
        action = None
        if proposed["kind"]:
            kind = proposed["kind"]
            key = (
                signing_reminder.remind_key(instance, proposed["number"])
                if kind == scheduling.REMIND_SIGNING
                else signing_reminder.lapse_key(instance)
            )
            if PendingAction.objects.filter(idempotency_key=key).exists():
                raise Refused("native_timer_already_exists")
            action = PendingAction.objects.create(
                kind=kind,
                subject_type="application",
                subject_id=application.public_ref,
                idempotency_key=key,
                input_ref=f"{instance.public_id}:{proposed['number']}"
                if kind == scheduling.REMIND_SIGNING
                else f"agreement:{instance.public_id}",
                due_at=instant(proposed["due_at"]),
                max_attempts=settings.CATALYST_REMINDER_STALE_DEFERRALS,
            )
        event(
            application,
            PREPARED,
            {
                **proposed,
                "instance": str(instance.public_id),
                "action": action.pk if action else None,
                "source_sha256": state["sha256"],
                "source_stopped_attested": True,
                "timers_reviewed": True,
                "note": note,
            },
            actor_type="staff",
            actor_ref=f"user:{user.pk}",
        )
        return application.events.get(
            kind=PREPARED, data__instance=str(instance.public_id)
        )


def quiet_since(application, action_id, default):
    receipt = application.events.filter(kind=PREPARED, data__action=action_id).first()
    return min(default, instant(receipt.data["quiet_since"])) if receipt else default
