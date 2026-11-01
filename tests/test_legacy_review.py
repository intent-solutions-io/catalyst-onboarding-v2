"""Imported pre-signing cases can reach the existing decision path without replaying effects."""

from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

from applications.models import ApplicationEvent
from assessments import decisions, pack, snapshot
from correspondence import staff_actions
from correspondence.common import Refused
from correspondence.models import ApprovedMessage, OutboundMessage, Question, StaffItem
from correspondence.roles import DECISION_MAKER
from firstgen import review
from firstgen.models import ImportedCase
from tests.test_first_generation_import import import_v1, populate, v1  # noqa: F401
from tests.test_outbound import staff
from tests.test_staff import logged_in, make_user
from workflow.models import AutomationPause, PendingAction


@pytest.fixture
def legacy(v1, privileged_reset, settings):
    ids = populate(v1)
    import_v1(v1)
    user = staff(
        SimpleNamespace(committed=privileged_reset), "handover-decider", DECISION_MAKER
    )
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute(
        "INSERT INTO accounts_user_user_permissions (user_id, permission_id) "
        "SELECT %s, id FROM auth_permission WHERE codename IN ('record_qualification_decision', 'view_application')",
        [user.pk],
    )
    settings.CATALYST_QUALIFICATION_AUTHORITY = "explicit_permission"
    return SimpleNamespace(user=user, ids=ids, source=v1, committed=privileged_reset)


def app(reference="CAT-NI00-0004"):
    return (
        ImportedCase.objects.select_related("application")
        .get(reference=reference)
        .application
    )


def prepare(application, user, **overrides):
    args = {
        "expected_digest": review.review_state(application)["digest"],
        "source_stopped": True,
        "history_reviewed": True,
        "note": "Verified source ownership; reviewed the old question and reply.",
    }
    args.update(overrides)
    return review.prepare(application.pk, user, **args)


def test_legacy_review_reaches_a_real_qualification_decision_without_replaying_mail(
    legacy,
):
    application = app()
    assert snapshot.manifest(application, pack.load()) is None
    receipt = prepare(application, legacy.user)
    application.refresh_from_db()
    assert application.stage == "awaiting_decision"
    assert receipt.data["source_stopped_attested"] is True
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    assert not PendingAction.objects.exists()
    assert not OutboundMessage.objects.exists() and not ApprovedMessage.objects.exists()
    assert (
        not Question.objects.exists()
    )  # old questions are history, never invented native answers
    state = decisions.decision_state(application)
    assert state["human_only_allowed"]
    assert state["manifest"]["first_generation"]["review_event"] == receipt.pk
    with pytest.raises(decisions.Refused, match="admit_refused_while_paused"):
        decisions.record_decision(
            application.pk,
            legacy.user,
            outcome="admit",
            reason_code="legacy_review",
            expected_digest=state["digest"],
            human_only_reason="Reviewed preserved legacy replies",
            rationale={
                c["id"]: {
                    "capability": "unknown",
                    "evidence_strength": "none",
                    "note": "Read the preserved history.",
                }
                for c in pack.load().criteria
            },
        )
    staff_actions.resume(
        application.pk,
        legacy.user,
        "Verified the frozen source and transfer of case ownership",
    )
    state = decisions.decision_state(application)
    decision = decisions.record_decision(
        application.pk,
        legacy.user,
        outcome="admit",
        reason_code="legacy_review",
        expected_digest=state["digest"],
        human_only_reason="Reviewed preserved legacy replies",
        rationale={
            c["id"]: {
                "capability": "unknown",
                "evidence_strength": "none",
                "note": "Read the preserved history.",
            }
            for c in pack.load().criteria
        },
    )
    application.refresh_from_db()
    assert application.stage == "admitted" and decision.basis == "human_only"
    assert decision.decision_inputs["first_generation"]["review_event"] == receipt.pk
    action = PendingAction.objects.get(subject_id=application.public_ref)
    assert (action.kind, action.status) == ("issue_nda", "held")
    assert not OutboundMessage.objects.exists() and not ApprovedMessage.objects.exists()


def test_legacy_review_is_idempotent_and_late_source_records_invalidate_the_snapshot(
    legacy,
):
    application = app()
    receipt = prepare(application, legacy.user)
    application.refresh_from_db()
    assert prepare(application, legacy.user).pk == receipt.pk
    before = review.assessment_context(application)
    legacy.source.event(
        legacy.ids["CAT-NI00-0004"],
        "needs_information",
        "needs_information",
        "late_reply",
        200,
    )
    import_v1(legacy.source)
    assert review.assessment_context(application) is False
    assert snapshot.manifest(application, pack.load()) is None
    replacement = prepare(application, legacy.user)
    after = review.assessment_context(application)
    assert (
        replacement.pk != receipt.pk
        and after["source_sha256"] != before["source_sha256"]
    )
    assert (
        ApplicationEvent.objects.filter(
            application=application, kind=review.REVIEWED
        ).count()
        == 2
    )
    assert not PendingAction.objects.exists()


def test_legacy_review_requires_authority_current_state_verification_and_attestations(
    legacy,
):
    application = app()
    reader = make_user(legacy.committed, "handover-reader")
    with pytest.raises(PermissionDenied):
        prepare(application, reader)
    for override, code in [
        ({"source_stopped": False}, "handover_and_history"),
        ({"history_reviewed": False}, "handover_and_history"),
        ({"note": "short"}, "review_note_required"),
        ({"expected_digest": "stale"}, "changed_since_shown"),
    ]:
        with pytest.raises(Refused, match=code):
            prepare(application, legacy.user, **override)
    unverified = app("CAT-RQ00-0001")
    with pytest.raises(Refused):
        prepare(unverified, legacy.user)
    assert not ApplicationEvent.objects.filter(kind=review.REVIEWED).exists()
    assert not PendingAction.objects.exists()


def test_legacy_review_refuses_provider_states_and_native_work_in_flight(legacy):
    for reference in (
        "CAT-ND00-0007",
        "CAT-SP00-0008",
        "CAT-PV00-0010",
        "CAT-AC00-0011",
    ):
        with pytest.raises(Refused, match="separate_reconciliation"):
            prepare(app(reference), legacy.user)
    application = app()
    PendingAction.objects.create(
        kind="synthetic_pending",
        subject_type="application",
        subject_id=application.public_ref,
        idempotency_key="legacy-review-synthetic-work",
    )
    with pytest.raises(Refused, match="native_work_in_flight"):
        prepare(application, legacy.user)
    assert not ApplicationEvent.objects.filter(kind=review.REVIEWED).exists()


def test_legacy_review_refuses_open_identity_items_and_keeps_the_pause(legacy):
    application = app()
    StaffItem.objects.create(
        application=application, reason_code="hard_bounce", dedupe_key="legacy-bounce"
    )
    with pytest.raises(Refused, match="identity_or_safety_item_open"):
        prepare(application, legacy.user)
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()


def test_legacy_review_cannot_be_used_for_a_routine_model_admit(legacy):
    application = app()
    prepare(application, legacy.user)
    application.refresh_from_db()
    with pytest.raises(
        decisions.Refused, match="legacy_history_requires_human_decision"
    ):
        decisions.record_routine_admit(
            application,
            SimpleNamespace(pk=1),
            rationale={},
            verdict={},
            actor="policy:test",
        )


def test_legacy_review_screen_requires_post_csrf_and_authority_and_preserves_refused_notes(
    legacy,
):
    application = app()
    url = reverse("firstgen_staff:prepare_review", args=[application.public_ref])
    client = logged_in(legacy.user)
    assert client.get(url).status_code == 405
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(legacy.user)
    assert strict.post(url, {}).status_code == 403
    reader = logged_in(make_user(legacy.committed, "handover-post-reader"))
    assert reader.post(url, {}).status_code == 403
    note = "Reviewed <b>the preserved history</b>"
    response = client.post(
        url, {"note": note, "digest": review.review_state(application)["digest"]}
    )
    assert response.status_code == 409 and "&lt;b&gt;" in response.content.decode()
    assert (
        '<input type="checkbox" name="source_stopped" value="yes" required>'
        in response.content.decode()
    )
    assert " checked" not in response.content.decode()
    response = client.post(
        url,
        {
            "note": note,
            "digest": review.review_state(application)["digest"],
            "source_stopped": "yes",
            "history_reviewed": "yes",
        },
    )
    assert response.status_code == 302
    shown = client.get(response.url).content.decode()
    assert reverse("assessments_staff:decision", args=[application.public_ref]) in shown
    assert not PendingAction.objects.exists()


def test_a_new_v2_reply_invalidates_review_and_must_finish_processing(legacy):
    from correspondence.models import InboundMessage

    application = app()
    prepare(application, legacy.user)
    application.refresh_from_db()
    original = review.assessment_context(application)
    staff_actions.resume(
        application.pk, legacy.user, "Confirmed the transfer of case ownership"
    )
    message = InboundMessage.objects.create(
        application=application,
        mailbox_ref="synthetic-legacy",
        original_sha256="a" * 64,
        derived_text_sha256="b" * 64,
        status="received",
        classification="human",
    )
    assert snapshot.manifest(application, pack.load()) is None
    with pytest.raises(Refused, match="inbound_review_in_flight"):
        prepare(application, legacy.user)
    InboundMessage.objects.filter(pk=message.pk).update(status="processed")
    prepare(
        application,
        legacy.user,
        note="Reviewed the newly received v2 reply and prior history",
    )
    assert (
        review.assessment_context(application)["source_sha256"]
        != original["source_sha256"]
    )
    assert not PendingAction.objects.exists()
    assert not AutomationPause.objects.filter(
        subject_id=application.public_ref
    ).exists()


def test_each_verified_pre_signing_source_state_reaches_human_review(legacy):
    for reference in (
        "CAT-RQ00-0002",
        "CAT-RV00-0003",
        "CAT-NI00-0004",
        "CAT-HD00-0005",
        "CAT-LP00-0006",
    ):
        application = app(reference)
        receipt = prepare(application, legacy.user)
        application.refresh_from_db()
        assert application.stage == "awaiting_decision", reference
        assert decisions.decision_state(application)["human_only_allowed"], reference
        assert review.assessment_context(application)["review_event"] == receipt.pk
        assert AutomationPause.objects.filter(
            subject_id=application.public_ref
        ).exists()
    assert not PendingAction.objects.exists() and not OutboundMessage.objects.exists()


def test_a_pre_signing_label_cannot_hide_an_envelope_or_unverified_contact(legacy):
    legacy.source.agreement(legacy.ids["CAT-NI00-0004"], "nda", "sent", 300)
    legacy.source.case(
        "reviewing",
        "Unverified Synthetic",
        "unverified-review@example.test",
        reference="CAT-UV00-0017",
        verified=False,
    )
    import_v1(legacy.source)
    with pytest.raises(
        Refused, match="legacy_provider_operations_require_reconciliation"
    ):
        prepare(app(), legacy.user)
    with pytest.raises(
        Refused, match="verified_contact_and_adopted_submission_required"
    ):
        prepare(app("CAT-UV00-0017"), legacy.user)
    assert not ApplicationEvent.objects.filter(kind=review.REVIEWED).exists()
    assert not PendingAction.objects.exists()


def test_late_v1_withdrawal_and_signing_states_cannot_reuse_the_initial_case_label(
    legacy,
):
    for reference, later_state in (
        ("CAT-NI00-0004", "withdrawn"),
        ("CAT-HD00-0005", "nda_pending"),
    ):
        legacy.source.event(
            legacy.ids[reference],
            "needs_information",
            later_state,
            "late_transition",
            310,
        )
    import_v1(legacy.source)
    for reference in ("CAT-NI00-0004", "CAT-HD00-0005"):
        with pytest.raises(Refused, match="later_legacy_state_requires_reconciliation"):
            prepare(app(reference), legacy.user)
    assert not ApplicationEvent.objects.filter(kind=review.REVIEWED).exists()
    assert not PendingAction.objects.exists()


def test_a_human_hold_can_be_reviewed_again_without_erasing_the_hold_or_pause(legacy):
    application = app()
    original = prepare(application, legacy.user)
    application.refresh_from_db()
    state = decisions.decision_state(application)
    held = decisions.record_decision(
        application.pk,
        legacy.user,
        outcome="hold",
        reason_code="legacy_review",
        expected_digest=state["digest"],
        human_only_reason="Need to review the preserved replies again",
        rationale={
            c["id"]: {
                "capability": "unknown",
                "evidence_strength": "none",
                "note": "Further human review required.",
            }
            for c in pack.load().criteria
        },
    )
    application.refresh_from_db()
    assert application.stage == "on_hold"
    renewed = prepare(application, legacy.user)
    application.refresh_from_db()
    assert renewed.pk != original.pk and application.stage == "awaiting_decision"
    held.refresh_from_db()
    assert held.outcome == "hold"
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    assert not PendingAction.objects.exists() and not OutboundMessage.objects.exists()
