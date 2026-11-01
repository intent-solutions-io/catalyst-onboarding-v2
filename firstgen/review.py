"""Recorded, human-reviewed continuation of imported cases before signing (bgl.23).

This is a handover attestation, not a command that stops v1. It never removes a pause,
sends a message, invents an answer or adopts a signing envelope.
"""

import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.db import transaction

from applications.models import Application, ApplicationEvent, Stage
from applications.stages import transition
from correspondence.common import Refused
from correspondence.models import Question, StaffItem
from correspondence.staff_items import clean_note
from workflow.models import AutomationPause, PendingAction

from .models import ImportedCase, ImportedRecord

REVIEWED = "legacy_review_prepared"
STAGES = (
    Stage.CONTACT_VERIFIED,
    Stage.ASSESSING,
    Stage.AWAITING_ANSWERS,
    Stage.AWAITING_DECISION,
    Stage.ON_HOLD,
)
SOURCE_STATES = ("requested", "reviewing", "needs_information", "held", "lapsed")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def source_state(application):
    case = ImportedCase.objects.filter(application=application).first()
    if case is None:
        return None
    records = list(
        ImportedRecord.objects.filter(application=application)
        .order_by("pk")
        .values(
            "id",
            "v1_table",
            "v1_id",
            "occurred_at",
            "message_id",
            "target",
            "data",
            "run_ref",
        )
    )
    adoption = application.adoptions.select_related("submission_version").first()
    version = str(adoption.submission_version.public_id) if adoption else ""
    inbox = list(
        application.inbound_messages.order_by("pk").values(
            "public_id",
            "derived_text_sha256",
            "status",
            "classification",
            "identity_state",
            "trust_decision",
        )
    )
    return {
        "case": case,
        "records": records,
        "version": version,
        "sha256": digest(
            {
                "case": case.pk,
                "source_state": case.v1_state,
                "resume_state": case.v1_resume_state,
                "run": case.run_ref,
                "version": version,
                "records": records,
                "inbox": inbox,
            }
        ),
    }


def assessment_context(application):
    """None for native cases, False until current imported history is reviewed, otherwise its receipt."""
    state = source_state(application)
    if state is None:
        return None
    receipt = application.events.filter(kind=REVIEWED).order_by("-pk").first()
    if receipt is None or receipt.data.get("source_sha256") != state["sha256"]:
        return False
    return {
        "review_event": receipt.pk,
        "source_sha256": state["sha256"],
        "version": state["version"],
    }


def can_review(user):
    from assessments.decisions import can_decide

    return can_decide(user) and user.has_perm("applications.view_application")


def review_state(application):
    source = source_state(application)
    if source is None:
        raise Refused("not_an_imported_case")
    pause = AutomationPause.objects.filter(
        subject_type="application", subject_id=application.public_ref
    ).first()
    return {
        **source,
        "pause": pause,
        "digest": digest(
            {
                "source": source["sha256"],
                "stage": application.stage,
                "verified": application.contact_verified_at,
                "pause": pause.pk if pause else None,
            }
        ),
    }


def prepare(
    application_id, user, *, expected_digest, source_stopped, history_reviewed, note
):
    if not can_review(user):
        raise PermissionDenied(
            "legacy_review_requires_decision_authority_and_dossier_access"
        )
    note = clean_note(note)
    if source_stopped is not True or history_reviewed is not True:
        raise Refused("handover_and_history_confirmation_required")
    if len(note) < 10:
        raise Refused("review_note_required")
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        state = review_state(application)
        case, pause = state["case"], state["pause"]
        if state["digest"] != expected_digest:
            raise Refused("changed_since_shown")
        if application.stage not in STAGES or case.v1_state not in SOURCE_STATES:
            raise Refused("legacy_state_requires_separate_reconciliation")
        # Top-up imports preserve the original case label. A later withdrawal or provider
        # transition must not be overridden by reviewing that stale label.
        later_states = [
            r
            for r in state["records"]
            if r["v1_table"] == "case_event"
            and str(r["run_ref"]) != str(case.run_ref)
            and r["data"].get("subject") == "case"
            and r["data"].get("to_state")
        ]
        if later_states:
            latest = max(
                later_states,
                key=lambda r: (
                    r["occurred_at"].isoformat() if r["occurred_at"] else "",
                    r["id"],
                ),
            )["data"]
            if latest["to_state"] not in SOURCE_STATES or (
                latest["to_state"] == "lapsed"
                and latest.get("from_state") != "needs_information"
            ):
                raise Refused("later_legacy_state_requires_reconciliation")
        if case.v1_state == "lapsed" and case.v1_resume_state not in (
            "",
            "needs_information",
        ):
            raise Refused("legacy_state_requires_separate_reconciliation")
        if not application.contact_verified_at or not state["version"]:
            raise Refused("verified_contact_and_adopted_submission_required")
        prior = application.events.filter(kind=REVIEWED).order_by("-pk").first()
        if prior is None and (
            pause is None
            or pause.actor_ref
            not in (
                "import:first-generation",
                "system:import:first-generation",
            )
        ):
            raise Refused("import_pause_required")
        # An earlier envelope/account remains consequential even when its historical status says closed.
        if any(
            r["v1_table"] in ("agreement", "mailbox_account", "case_release")
            for r in state["records"]
        ):
            raise Refused("legacy_provider_operations_require_reconciliation")
        if (
            application.agreements.exists()
            or application.qualification_decisions.exclude(outcome="hold").exists()
            or (prior is None and application.qualification_decisions.exists())
        ):
            raise Refused("native_progress_requires_separate_review")
        if application.inbound_messages.filter(
            status__in=("received", "awaiting_processing")
        ).exists():
            raise Refused("inbound_review_in_flight")
        if PendingAction.objects.filter(
            subject_type="application",
            subject_id=application.public_ref,
            status__in=("queued", "running", "held"),
        ).exists():
            raise Refused("native_work_in_flight")
        from assessments.decisions import IDENTITY_ITEMS
        from correspondence.staff_actions import PAUSE_CAUSES

        if StaffItem.objects.filter(
            application=application,
            status="open",
            reason_code__in=(*IDENTITY_ITEMS, *PAUSE_CAUSES),
        ).exists():
            raise Refused("identity_or_safety_item_open")
        if (
            Question.objects.filter(application=application)
            .exclude(status__in=("satisfied", "withdrawn"))
            .exists()
        ):
            raise Refused("native_question_pending")
        if (
            prior
            and prior.data.get("source_sha256") == state["sha256"]
            and application.stage == Stage.AWAITING_DECISION
        ):
            return prior
        transition(
            application.pk,
            STAGES,
            Stage.AWAITING_DECISION,
            event_kind=REVIEWED,
            actor_type=ApplicationEvent.ActorType.STAFF,
            actor_ref=f"user:{user.pk}",
            data={
                "source_sha256": state["sha256"],
                "version": state["version"],
                "record_count": len(state["records"]),
                "source_stopped_attested": True,
                "history_reviewed": True,
                "note": note,
                "disposition": "prior_questions_to_human_review",
            },
        )
        return ApplicationEvent.objects.filter(
            application=application, kind=REVIEWED
        ).latest("pk")
