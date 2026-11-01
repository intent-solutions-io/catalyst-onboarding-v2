"""Adopt an existing v1 envelope without creating or replaying an agreement (bgl.23)."""

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Now

from agreements import completion, handlers, provider, services
from agreements.models import (
    AgreementInstance,
    AgreementRecipient,
    AgreementTemplateVersion,
)
from applications.models import Application, Stage
from correspondence.common import Refused
from correspondence.messages import verified_address
from correspondence.models import StaffItem
from correspondence.staff_items import clean_note, event
from workflow.models import PendingAction

from . import mapping, review
from .models import ImportedRecord

ADOPTED = "legacy_envelope_adopted"
WAITING = "legacy_envelope_requires_adoption"


def unadopted(application, type_key):
    """Even an unknown historical status blocks a fresh create until explicitly reconciled."""
    records = list(
        ImportedRecord.objects.filter(
            application=application, v1_table="agreement", data__document_type=type_key
        )
    )
    if not records:
        return []
    known = set(
        application.agreements.exclude(envelope_id="").values_list(
            "envelope_id", flat=True
        )
    )
    return [
        r
        for r in records
        if r.data.get("provider_ref") and r.data["provider_ref"] not in known
    ]


def can_adopt(user):
    return review.can_review(user) and services.can(user, "manage_agreements")


def _recipients(application, version):
    address = verified_address(application)
    if not address:
        raise Refused("verified_contact_required")
    slots = version.recipient_slots or {}
    role, company = (
        settings.CATALYST_AGREEMENT_COMPANY_ROLE,
        settings.CATALYST_AGREEMENT_COMPANY_EMAIL,
    )
    expected_slots = {"SIGNER:1"} | ({f"{role}:2"} if company else set())
    if set(slots) != expected_slots or any(
        type(v) is not int or v <= 0 for v in slots.values()
    ):
        raise Refused("historical_template_recipient_configuration_required")
    rows = [
        {
            "email": address,
            "name": application.display_name,
            "role": "SIGNER",
            "signing_order": 1,
            "required": True,
            "who": "applicant",
        }
    ]
    if company:
        if (
            company.lower() == address.lower()
            or not settings.CATALYST_AGREEMENT_COMPANY_NAME
        ):
            raise Refused("company_recipient_configuration_required")
        rows.append(
            {
                "email": company,
                "name": settings.CATALYST_AGREEMENT_COMPANY_NAME,
                "role": role,
                "signing_order": 2,
                "required": True,
                "who": "staff",
            }
        )
    return rows


def _state(application, record_id, version_id, expected_digest):
    state = review.review_state(application)
    if state["digest"] != expected_digest:
        raise Refused("changed_since_shown")
    case, pause = state["case"], state["pause"]
    if application.stage != Stage.AGREEMENTS or case.v1_state not in (
        "nda_pending",
        "setup_pending",
        "lapsed",
    ):
        raise Refused("legacy_state_requires_separate_reconciliation")
    if case.v1_state == "lapsed" and case.v1_resume_state not in (
        "nda_pending",
        "setup_pending",
    ):
        raise Refused("legacy_state_requires_separate_reconciliation")
    if pause is None:
        raise Refused("pause_required_for_envelope_handover")
    if (
        pause.actor_ref
        not in ("import:first-generation", "system:import:first-generation")
        and not application.events.filter(kind=ADOPTED).exists()
    ):
        raise Refused("import_pause_required")
    record = ImportedRecord.objects.filter(
        pk=record_id, application=application, v1_table="agreement"
    ).first()
    version = (
        AgreementTemplateVersion.objects.select_related("agreement_type")
        .filter(pk=version_id, status="approved")
        .first()
    )
    if (
        record is None
        or version is None
        or record.data.get("document_type") != version.agreement_type.key
    ):
        raise Refused("approved_matching_template_and_source_record_required")
    data = record.data
    if (
        data.get("status")
        not in (*mapping.OPEN_AGREEMENT, *mapping.COMPLETED_AGREEMENT)
        or not provider.ENVELOPE_ID.fullmatch(str(data.get("provider_ref") or ""))
        or not provider.ENVELOPE_ID.fullmatch(str(data.get("external_ref") or ""))
    ):
        raise Refused("legacy_envelope_identity_or_status_requires_reconciliation")
    if (
        AgreementInstance.objects.filter(
            Q(envelope_id=data["provider_ref"]) | Q(external_key=data["external_ref"])
        )
        .exclude(application=application)
        .exists()
    ):
        raise Refused("envelope_already_owned_by_another_case")
    recipients = _recipients(application, version)
    existing = application.agreements.filter(envelope_id=data["provider_ref"]).first()
    if existing is not None:
        if (
            existing.external_key != data["external_ref"]
            or existing.template_version_id != version.pk
            or not application.events.filter(
                kind=ADOPTED,
                data__record=record.pk,
                data__instance=str(existing.public_id),
            ).exists()
        ):
            raise Refused("existing_envelope_requires_reconciliation")
        return state, record, version, recipients, existing
    if application.agreements.filter(agreement_type=version.agreement_type).exists():
        raise Refused("native_agreement_requires_reconciliation")
    if len(unadopted(application, version.agreement_type.key)) != 1:
        raise Refused("multiple_legacy_envelopes_require_reconciliation")
    from assessments.decisions import IDENTITY_ITEMS
    from correspondence.staff_actions import PAUSE_CAUSES

    if (
        completion.stopped(application)
        or StaffItem.objects.filter(
            application=application,
            status="open",
            reason_code__in=(*IDENTITY_ITEMS, *PAUSE_CAUSES),
        ).exists()
    ):
        raise Refused("identity_or_safety_item_open")
    if (
        PendingAction.objects.filter(
            subject_type="application",
            subject_id=application.public_ref,
            status__in=("queued", "running", "held"),
        )
        .exclude(
            kind__in=(
                completion.READ,
                completion.ADVANCE,
                "store_agreement",
                "countersign_agreement",
            )
        )
        .exists()
    ):
        raise Refused("native_work_requires_reconciliation")
    if version.agreement_type.key == "user_agreement":
        nda = application.agreements.filter(
            agreement_type__key="nda",
            signing_status="signing_complete_verified",
            replaced_at__isnull=True,
        ).first()
        if nda is None or completion.integrity_hold_open(nda):
            raise Refused("verified_native_nda_required_before_ua_adoption")
    # A top-up does not overwrite the initial case label: don't resurrect a later final outcome.
    later = [
        r
        for r in state["records"]
        if r["v1_table"] == "case_event"
        and str(r["run_ref"]) != str(case.run_ref)
        and r["data"].get("subject") == "case"
        and r["data"].get("to_state")
    ]
    if later:
        latest = max(
            later,
            key=lambda r: (
                r["occurred_at"].isoformat() if r["occurred_at"] else "",
                r["id"],
            ),
        )
        if latest["data"]["to_state"] not in ("nda_pending", "setup_pending", "lapsed"):
            raise Refused("later_legacy_state_requires_reconciliation")
    return state, record, version, recipients, None


def adopt(
    application_id,
    record_id,
    version_id,
    user,
    *,
    expected_digest,
    source_stopped,
    mapping_reviewed,
    note,
):
    if not can_adopt(user):
        raise PermissionDenied("legacy_envelope_handover_authority_required")
    note = clean_note(note)
    if source_stopped is not True or mapping_reviewed is not True or len(note) < 10:
        raise Refused("handover_template_and_recipient_confirmation_required")
    if transaction.get_connection().in_atomic_block:
        raise RuntimeError("provider reads must run outside a database transaction")
    application = Application.objects.get(pk=application_id)
    state, record, version, recipients, existing = _state(
        application, record_id, version_id, expected_digest
    )
    if existing is not None:
        return existing
    fingerprint = review.digest(
        {"template": services.template_digest(version), "recipients": recipients}
    )
    env = provider.read(record.data["provider_ref"])
    if (
        env.id != record.data["provider_ref"]
        or env.external_id != record.data["external_ref"]
        or env.type != "DOCUMENT"
        or env.template_number != version.provider_template_number
        or env.status not in ("PENDING", "COMPLETED", "DRAFT")
    ):
        raise Refused("provider_identity_or_status_mismatch")
    ours = sorted(
        (r["email"].lower(), r["role"], r["signing_order"]) for r in recipients
    )
    theirs = [(r.email.lower(), r.role, r.signing_order) for r in env.recipients]
    if (
        len(theirs) != len(ours)
        or any(r not in ours for r in theirs)
        or len(set(theirs)) != len(theirs)
    ):
        raise Refused("provider_recipients_mismatch")
    if env.status == "DRAFT" and record.data["status"] != "prepared":
        raise Refused("provider_status_disagrees_with_legacy_send")
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        state, record, version, recipients, existing = _state(
            application, record_id, version_id, expected_digest
        )
        if existing is not None:
            return existing
        if (
            review.digest(
                {
                    "template": services.template_digest(version),
                    "recipients": recipients,
                }
            )
            != fingerprint
        ):
            raise Refused("changed_since_provider_read")
        instance = AgreementInstance.objects.create(
            application=application,
            agreement_type=version.agreement_type,
            template_version=version,
            external_key=record.data["external_ref"],
        )
        for row in recipients:
            AgreementRecipient.objects.create(instance=instance, **row)
        # Preserve the real identity; neither a create attempt nor a new external key is invented.
        status = "distribute_pending" if env.status == "DRAFT" else "issued"
        AgreementInstance.objects.filter(pk=instance.pk).update(
            envelope_id=env.id, issue_status=status, updated_at=Now()
        )
        instance.refresh_from_db()
        event(
            application,
            ADOPTED,
            {
                "record": record.pk,
                "instance": str(instance.public_id),
                "source_sha256": state["sha256"],
                "template": version.pk,
                "template_sha256": services.template_digest(version),
                "source_stopped_attested": True,
                "mapping_reviewed": True,
                "provider_status": env.status,
                "note": note,
            },
            actor_ref=f"user:{user.pk}",
        )
        if env.status == "DRAFT":
            handlers.enqueue_distribute(
                instance
            )  # automated; the preserved pause prevents sending
        else:
            completion.enqueue_read(
                instance
            )  # only the normal fresh read can verify signatures and queue custody
        return instance
