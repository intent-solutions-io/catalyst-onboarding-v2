"""Legacy envelopes retain their identities and enter the native read-verification path."""

import hashlib
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

from agreements import completion, provider, services
from agreements.models import (
    AgreementInstance,
    AgreementTemplateVersion,
    AgreementType,
    EnvelopeAttempt,
    ProviderObservation,
)
from applications.models import ApplicationEvent
from config import runtime
from correspondence.common import Refused
from correspondence.models import OutboundMessage
from firstgen import agreements as adoption, review
from firstgen.models import ImportedRecord
from tests.documenso_fake import FakeDocumenso
from tests.test_agreements import configure, grant
from tests.test_inbound import tls  # noqa: F401
from tests.test_legacy_review import app, legacy, v1  # noqa: F401
from tests.test_first_generation_import import import_v1
from tests.test_staff import logged_in, make_user
from workflow import ledger
from workflow.models import AutomationPause, PendingAction


@pytest.fixture
def envelopes(legacy, tls, settings, monkeypatch):
    fake = FakeDocumenso(tls.documenso).start()
    configure(settings, fake, tls)
    settings.CATALYST_AGREEMENT_DEADLINE_SECONDS = 2
    settings.CATALYST_AGREEMENT_COMPANY_EMAIL = "company@example.test"
    settings.CATALYST_AGREEMENT_COMPANY_NAME = "Hedy Example"
    settings.CATALYST_AGREEMENT_COMPANY_ROLE = "APPROVER"
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    grant(legacy, legacy.user, "manage_agreements")
    grant(legacy, legacy.user, "approve_agreement_template")
    versions = {}
    for key, number in (("nda", 101), ("user_agreement", 102)):
        ref, _, _ = fake.template(ref=f"template_{key}", number=number)
        fake.templates[ref]["slots"][7002] = "APPROVER"
        version = AgreementTemplateVersion.objects.create(
            agreement_type=AgreementType.objects.get(key=key),
            version=1,
            provider_template_ref=ref,
            provider_template_number=number,
            recipient_slots={"SIGNER:1": 7001, "APPROVER:2": 7002},
            pdf_sha256=hashlib.sha256(b"synthetic historical template").hexdigest(),
        )
        services.approve_template_version(
            version.pk, legacy.user, services.template_digest(version)
        )
        version.refresh_from_db()
        versions[key] = version
    try:
        yield SimpleNamespace(**vars(legacy), fake=fake, versions=versions)
    finally:
        fake.stop()


def source_record(application, type_key="nda"):
    return ImportedRecord.objects.get(
        application=application, v1_table="agreement", data__document_type=type_key
    )


def provider_envelope(env, application, type_key="nda", status="PENDING"):
    record = source_record(application, type_key)
    version = env.versions[type_key]
    data = env.fake._create(
        version.provider_template_ref,
        record.data["external_ref"],
        [
            {
                "id": 7001,
                "email": application.email,
                "name": application.display_name,
                "signingOrder": 1,
            },
            {
                "id": 7002,
                "email": "company@example.test",
                "name": "Hedy Example",
                "signingOrder": 2,
            },
        ],
        status=status,
    )
    old_id = data["id"]
    data["id"] = record.data["provider_ref"]
    env.fake.envelopes[data["id"]] = env.fake.envelopes.pop(old_id)
    return data


def adopt(env, application, type_key="nda", **overrides):
    args = dict(
        expected_digest=review.review_state(application)["digest"],
        source_stopped=True,
        mapping_reviewed=True,
        note="Verified source freeze, historical template and recipient ownership",
    )
    args.update(overrides)
    return adoption.adopt(
        application.pk,
        source_record(application, type_key).pk,
        env.versions[type_key].pk,
        env.user,
        **args,
    )


def read_once():
    handler = completion.ReadAgreement()
    claim = ledger.claim_next({completion.READ: handler})
    assert claim is not None
    handler.run(claim)


@pytest.mark.parametrize("legacy", ["unverified"], indirect=True)
def test_unverified_signing_case_can_confirm_contact_and_adopt_its_original_envelope(
    envelopes, settings, monkeypatch
):
    from tests.test_legacy_review import verify_imported_contact

    application = app("CAT-ND00-0007")
    data = provider_envelope(envelopes, application)
    resumed, item, processing = verify_imported_contact(
        envelopes, application, settings, monkeypatch
    )
    with pytest.raises(Refused, match="identity_or_safety_item_open"):
        adopt(envelopes, application)
    assert not envelopes.fake.requests
    processing.resolve_exception(
        item.pk,
        "acknowledge",
        envelopes.user,
        "Reviewed verified contact before envelope adoption",
    )
    instance = adopt(envelopes, application)
    assert instance.envelope_id == data["id"]
    receipt = application.events.get(kind=adoption.ADOPTED)
    assert receipt.data["import_resume_event"] == resumed.pk
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    assert not any(method == "POST" for method, *_ in envelopes.fake.requests)


def test_a_pending_legacy_envelope_is_adopted_once_without_create_send_or_unpause(
    envelopes,
):
    application = app("CAT-ND00-0007")
    data = provider_envelope(envelopes, application)
    instance = adopt(envelopes, application)
    assert (
        instance.envelope_id == data["id"]
        and instance.external_key == data["externalId"]
    )
    assert (
        instance.issue_status == "issued" and instance.signing_status == "not_started"
    )
    assert adopt(envelopes, application).pk == instance.pk
    assert instance.recipients.count() == 2
    assert PendingAction.objects.filter(kind="read_agreement").count() == 1
    assert not EnvelopeAttempt.objects.exists() and not OutboundMessage.objects.exists()
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    assert not any(r["method"] == "POST" for r in envelopes.fake.requests)
    assert len(envelopes.fake.envelopes) == 1
    assert ApplicationEvent.objects.filter(kind=adoption.ADOPTED).count() == 1


def test_only_the_native_provider_read_verifies_the_legacy_nda_before_ua_adoption(
    envelopes,
):
    application = app("CAT-SP00-0008")
    nda = provider_envelope(envelopes, application)
    provider_envelope(envelopes, application, "user_agreement")
    assert completion.next_step(application)[2] == adoption.WAITING
    with pytest.raises(Refused, match="verified_native_nda_required"):
        adopt(envelopes, application, "user_agreement")
    envelopes.fake.sign(nda["id"], 0)
    envelopes.fake.sign(nda["id"], 1)
    instance = adopt(envelopes, application)
    assert (
        instance.signing_status == "not_started"
        and not ProviderObservation.objects.exists()
    )
    read_once()
    instance.refresh_from_db()
    assert (
        instance.signing_status == "signing_complete_verified"
        and instance.custody_status == "pending"
    )
    observation = ProviderObservation.objects.get(instance=instance, source="read")
    assert (
        observation.identity_match
        and observation.recipients_match
        and observation.all_required_signed
    )
    ua = adopt(envelopes, application, "user_agreement")
    assert (
        ua.envelope_id
        == source_record(application, "user_agreement").data["provider_ref"]
    )
    assert set(PendingAction.objects.values_list("kind", flat=True)) <= {
        "read_agreement",
        "store_agreement",
        "advance_agreements",
    }
    assert not EnvelopeAttempt.objects.exists() and not OutboundMessage.objects.exists()
    assert not any(r["method"] == "POST" for r in envelopes.fake.requests)


def test_adoption_refuses_wrong_key_template_address_role_and_order(envelopes):
    application = app("CAT-ND00-0007")
    data = provider_envelope(envelopes, application)
    changes = [
        (data, "externalId", "wrong-key"),
        (data, "templateId", 999),
        (data["recipients"][0], "email", "wrong@example.test"),
        (data["recipients"][1], "role", "SIGNER"),
        (data["recipients"][1], "signingOrder", 1),
    ]
    for target, key, value in changes:
        original = target[key]
        target[key] = value
        with pytest.raises(Refused, match="provider_.*mismatch"):
            adopt(envelopes, application)
        target[key] = original
    assert not AgreementInstance.objects.exists() and not PendingAction.objects.exists()
    assert not ApplicationEvent.objects.filter(kind=adoption.ADOPTED).exists()


def test_adoption_requires_handover_authority_and_current_pause(envelopes):
    application = app("CAT-ND00-0007")
    provider_envelope(envelopes, application)
    for overrides in (
        {"source_stopped": False},
        {"mapping_reviewed": False},
        {"note": "short"},
        {"expected_digest": "stale"},
    ):
        with pytest.raises(Refused):
            adopt(envelopes, application, **overrides)
    reader = make_user(envelopes.committed, "envelope-reader")
    with pytest.raises(PermissionDenied):
        adoption.adopt(
            application.pk,
            source_record(application).pk,
            envelopes.versions["nda"].pk,
            reader,
            expected_digest="",
            source_stopped=True,
            mapping_reviewed=True,
            note="Reviewed handover",
        )
    from correspondence import staff_actions

    staff_actions.resume(
        application.pk, envelopes.user, "Confirmed the frozen source ownership transfer"
    )
    with pytest.raises(Refused, match="pause_required"):
        adopt(envelopes, application)
    assert not envelopes.fake.requests
    assert not AgreementInstance.objects.exists()


def test_adoption_rechecks_history_after_the_provider_read(envelopes, monkeypatch):
    application = app("CAT-ND00-0007")
    provider_envelope(envelopes, application)
    real_read = provider.read

    def changed(identity):
        result = real_read(identity)
        envelopes.source.event(
            envelopes.ids["CAT-ND00-0007"], "nda_pending", "withdrawn", "withdrawn", 400
        )
        import_v1(envelopes.source)
        return result

    monkeypatch.setattr(provider, "read", changed)
    with pytest.raises(Refused, match="changed_since_shown"):
        adopt(envelopes, application)
    assert not AgreementInstance.objects.exists() and not PendingAction.objects.exists()


def test_the_handover_form_requires_post_csrf_and_matching_case_records(envelopes):
    application = app("CAT-ND00-0007")
    provider_envelope(envelopes, application)
    url = reverse("firstgen_staff:adopt_envelope", args=[application.public_ref])
    client = logged_in(envelopes.user)
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(envelopes.user)
    assert (
        client.get(url).status_code == 405 and strict.post(url, {}).status_code == 403
    )
    form = {
        "record": source_record(application).pk,
        "template": envelopes.versions["nda"].pk,
        "digest": review.review_state(application)["digest"],
        "source_stopped": "yes",
        "mapping_reviewed": "yes",
        "note": "Reviewed <b>history</b> and verified frozen source",
    }
    refused = client.post(
        url, {**form, "record": source_record(app("CAT-SP00-0008")).pk}
    )
    assert refused.status_code == 409 and "&lt;b&gt;" in refused.content.decode()
    assert not AgreementInstance.objects.exists()
    assert client.post(url, form).status_code == 302
    assert not any(r["method"] == "POST" for r in envelopes.fake.requests)


def test_a_prepared_draft_distributes_the_same_envelope_only_after_separate_resume(
    envelopes,
):
    from agreements import handlers
    from correspondence import staff_actions

    case_id = envelopes.source.case(
        "nda_pending",
        "Draft Synthetic",
        "draft@example.test",
        reference="CAT-DR00-0018",
    )
    envelopes.source.agreement(case_id, "nda", "prepared", 300)
    import_v1(envelopes.source)
    application = app("CAT-DR00-0018")
    data = provider_envelope(envelopes, application, status="DRAFT")
    instance = adopt(envelopes, application)
    handler = handlers.DistributeAgreement()
    assert instance.issue_status == "distribute_pending"
    assert ledger.claim_next({handler.kind: handler}) is None
    assert not any(r["method"] == "POST" for r in envelopes.fake.requests)
    staff_actions.resume(
        application.pk,
        envelopes.user,
        "Verified the source freeze and reviewed draft distribution",
    )
    claim = ledger.claim_next({handler.kind: handler})
    assert claim is not None
    handler.run(claim)
    instance.refresh_from_db()
    assert instance.issue_status == "issued" and instance.envelope_id == data["id"]
    assert len(envelopes.fake.envelopes) == 1
    assert len(envelopes.fake.calls("POST", "/envelope/distribute")) == 1
    assert not envelopes.fake.calls("POST", "/envelope/use")
    handler.run(claim)  # a stale delivery cannot send again
    assert len(envelopes.fake.calls("POST", "/envelope/distribute")) == 1


def test_provider_refusal_and_existing_cross_case_ownership_leave_no_adoption(
    envelopes,
):
    application = app("CAT-ND00-0007")
    data = provider_envelope(envelopes, application)
    envelopes.fake.fault("GET /envelope/", ("status", 429, {"Retry-After": "3"}))
    with pytest.raises(provider.ProviderError) as error:
        adopt(envelopes, application)
    assert error.value.status == 429 and error.value.retry_after == 3
    data["status"] = "CANCELLED"
    with pytest.raises(Refused, match="provider_identity_or_status_mismatch"):
        adopt(envelopes, application)
    data["status"] = "PENDING"
    other = AgreementInstance.objects.create(
        application=app("CAT-SP00-0008"),
        agreement_type=envelopes.versions["nda"].agreement_type,
        template_version=envelopes.versions["nda"],
        external_key=data["externalId"],
    )
    AgreementInstance.objects.filter(pk=other.pk).update(envelope_id=data["id"])
    with pytest.raises(Refused, match="envelope_already_owned_by_another_case"):
        adopt(envelopes, application)
    assert AgreementInstance.objects.count() == 1
    assert not ApplicationEvent.objects.filter(kind=adoption.ADOPTED).exists()
    assert not PendingAction.objects.exists()


def test_an_older_member_reference_cannot_hide_a_new_unadopted_envelope(envelopes):
    application = app("CAT-RP00-0009")
    assert completion.next_step(application)[2] == "all_passed"
    envelopes.source.agreement(envelopes.ids["CAT-RP00-0009"], "nda", "sent", 400)
    import_v1(envelopes.source)
    assert completion.next_step(application)[2] == adoption.WAITING
    assert not PendingAction.objects.exists()


def test_both_old_envelopes_reach_native_custody_and_one_held_provisioning_handoff(
    envelopes, settings, tmp_path
):
    from agreements import custody
    from agreements.models import StoredDocument
    from correspondence import staff_actions
    from tests.test_agreement_custody import custody_keys

    settings.CATALYST_AGREEMENT_STORAGE_DIR = str(tmp_path / "custody")
    custody_keys(settings, tmp_path)
    application = app("CAT-SP00-0008")
    for type_key in ("nda", "user_agreement"):
        data = provider_envelope(envelopes, application, type_key)
        envelopes.fake.sign(data["id"], 0)
        envelopes.fake.sign(data["id"], 1)
        instance = adopt(envelopes, application, type_key)
        read_once()
        handler = custody.StoreAgreement()
        claim = ledger.claim_next({handler.kind: handler})
        assert claim is not None
        handler.run(claim)
        instance.refresh_from_db()
        assert instance.signing_status == "signing_complete_verified"
        assert instance.custody_status == "stored_verified"
        assert StoredDocument.objects.filter(
            instance=instance, envelope_id=data["id"]
        ).exists()
    handler = completion.AdvanceAgreements()
    assert ledger.claim_next({handler.kind: handler}) is None  # still paused
    staff_actions.resume(
        application.pk,
        envelopes.user,
        "Verified all legacy envelopes and frozen source ownership",
    )
    claim = ledger.claim_next({handler.kind: handler})
    assert claim is not None
    handler.run(claim)
    application.refresh_from_db()
    assert application.stage == "agreements_complete"
    handoff = PendingAction.objects.get(
        kind="provision", subject_id=application.public_ref
    )
    assert handoff.status == "held"
    handler.run(claim)
    assert (
        PendingAction.objects.filter(
            kind="provision", subject_id=application.public_ref
        ).count()
        == 1
    )
    assert len(envelopes.fake.envelopes) == 2
    assert not any(r["method"] == "POST" for r in envelopes.fake.requests)
    assert not EnvelopeAttempt.objects.exists() and not OutboundMessage.objects.exists()


@pytest.mark.parametrize(
    "source_from,source_to", [("nda_pending", "withdrawn"), ("active", "lapsed")]
)
def test_late_source_final_states_and_duplicate_envelopes_are_refused_before_provider_access(
    envelopes,
    source_from,
    source_to,
):
    envelopes.source.event(
        envelopes.ids["CAT-ND00-0007"], source_from, source_to, "late_state", 400
    )
    envelopes.source.agreement(envelopes.ids["CAT-SP00-0008"], "nda", "sent", 400)
    import_v1(envelopes.source)
    with pytest.raises(Refused, match="later_legacy_state_requires_reconciliation"):
        adopt(envelopes, app("CAT-ND00-0007"))
    application = app("CAT-SP00-0008")
    original = ImportedRecord.objects.filter(
        application=application, v1_table="agreement", data__document_type="nda"
    ).first()
    with pytest.raises(
        Refused, match="multiple_legacy_envelopes_require_reconciliation"
    ):
        adoption.adopt(
            application.pk,
            original.pk,
            envelopes.versions["nda"].pk,
            envelopes.user,
            expected_digest=review.review_state(application)["digest"],
            source_stopped=True,
            mapping_reviewed=True,
            note="Reviewed source ownership and the historical template",
        )
    assert not envelopes.fake.requests
    assert not AgreementInstance.objects.exists() and not PendingAction.objects.exists()
