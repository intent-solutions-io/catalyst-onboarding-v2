"""Approved self-report admission remains distinct from independent evidence."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from assessments import approval, clarify, pack, policy, schema, snapshot


def activate(settings):
    settings.CATALYST_ENV = "production"
    settings.CATALYST_PARITY_ACTIVE = True
    settings.CATALYST_ASSESSMENT_LIVE_ACTIVATION = 1
    settings.CATALYST_ASSESSMENT_MODEL = "minimax:MiniMax-M3"
    settings.CATALYST_ROUTINE_ADVANCE_ACTIVATION = 2
    settings.CATALYST_ASSESSMENT_PROMPT_PACK = "assessment_v4"
    settings.CATALYST_SELECTION_POLICY = "production-admission-20261102"
    settings.CATALYST_SELECTION_POLICY_PACKS = {
        "production-admission-20261102": "assessment_v4"
    }


def test_public_automated_intake_requires_and_displays_the_approved_notice(
    settings, privileged_reset
):
    from applications import notices, views
    from tests.test_invitation import ensure_notice_templates
    from tests.test_intake_notice import real_version

    ensure_notice_templates()
    settings.CATALYST_INTAKE_MODE = "open"
    activate(settings)
    with pytest.raises(notices.Unavailable):
        views._data_notice()
    real_version(
        privileged_reset,
        "data_notice",
        2,
        "MiniMax helps review your submitted information.",
    )
    assert "MiniMax" in views._data_notice().text
    settings.CATALYST_PARITY_ACTIVE = False
    assert views._data_notice() is None


def test_confirmation_queues_research_only_for_the_bound_production_policy(
    settings, db
):
    from applications import confirmation
    from tests.test_confirmation import intake, active_challenge, version
    from workflow.models import PendingAction
    from assessments.decisions import cohort_boundary

    app = intake(reason="Practice testing streaming parsers. Contact ada@example.test.")
    activate(settings)
    assert cohort_boundary() is False
    confirmation.confirm(active_challenge(app).public_id, version(app, 1).public_id)
    assert (
        PendingAction.objects.get(
            subject_id=app.public_ref, kind="start_evidence_collection"
        ).status
        == "queued"
    )
    current = pack.load()
    request = snapshot.build_request(app, snapshot.manifest(app, current), current)
    assert "submitted_fields.reason" in request.fields
    assert "Practice testing streaming parsers" in request.prompt
    assert "ada@example.test" not in request.prompt
    assert "[basis=self_report]" in request.prompt


@pytest.mark.parametrize(
    "change,value",
    [
        ("CATALYST_PARITY_ACTIVE", False),
        ("CATALYST_ASSESSMENT_MODEL", "none"),
        ("CATALYST_ASSESSMENT_LIVE_ACTIVATION", 0),
        ("CATALYST_ROUTINE_ADVANCE_ACTIVATION", 1),
        ("CATALYST_SELECTION_POLICY_PACKS", {}),
        ("CATALYST_ASSESSMENT_PROMPT_PACK", "assessment_v3"),
    ],
)
def test_incomplete_activation_keeps_the_cohort_boundary(settings, change, value):
    from assessments.decisions import cohort_boundary
    from config.parity import automated_admission_enabled

    activate(settings)
    setattr(settings, change, value)
    assert automated_admission_enabled(settings) is False
    assert cohort_boundary() is True


def reported():
    rubric = pack.load("assessment_v4")
    text = "I implemented the parser and want to practice testing streaming parsers."
    findings = [
        {
            "criterion_id": c["id"],
            "rating": "partly_supported",
            "summary": "A specific applicant statement.",
            "citations": [{"evidence_alias": "C1", "quote": text}],
        }
        for c in rubric.criteria
    ]
    result = schema.AssessmentOutput.model_validate(
        {
            "schema_version": "3",
            "criteria": findings,
            "recommendation": "admit",
            "recommendation_basis": "All required statements are specific.",
            "basis_criteria": [c["id"] for c in rubric.criteria],
            "confidence": "high",
            "proposed_questions": [],
            "injection_suspected": False,
            "injection_citations": [],
            "limitations": [],
        }
    )
    facts = policy.Facts(
        required=frozenset(c["id"] for c in rubric.criteria),
        self_report=frozenset(c["id"] for c in rubric.criteria),
        cohort_boundary=False,
        identity_item_open=False,
        paused=False,
        contact_verified=True,
        open_question=False,
        evidence_pending=False,
    )
    request = SimpleNamespace(
        criteria=rubric.criteria, items={"C1": SimpleNamespace(text=text)}, missing=[]
    )
    return result, facts, request


def test_approved_self_report_advances_without_claiming_independent_support():
    result, facts, request = reported()
    assert not schema.problems(result, request)
    assert policy.decide(result, facts).outcome == policy.ADVANCE
    assert (
        policy.decide(result, replace(facts, self_report=frozenset())).outcome
        == policy.NEEDS_HUMAN
    )
    result.criteria[0].rating = "supported"
    assert "claims_only_rating_above_partly_supported" in schema.problems(
        result, request
    )


@pytest.mark.parametrize(
    "field",
    [
        "cohort_boundary",
        "identity_item_open",
        "paused",
        "open_question",
        "evidence_pending",
    ],
)
def test_self_report_does_not_bypass_workflow_holds(field):
    result, facts, _ = reported()
    assert (
        policy.decide(result, replace(facts, **{field: True})).outcome != policy.ADVANCE
    )


def test_missing_goal_and_declines_cannot_automatically_advance():
    result, facts, _ = reported()
    result.criteria[-1].rating = "insufficient_evidence"
    result.criteria[-1].citations = []
    assert policy.decide(result, facts).outcome == policy.NEEDS_HUMAN
    result.recommendation = "decline"
    assert policy.decide(result, facts).reason == "decline_is_never_automatic"


def test_production_pack_is_explicit_and_historical_packs_are_unchanged(settings):
    assert pack.load().rubric["synthetic"] is True
    settings.CATALYST_ASSESSMENT_PROMPT_PACK = "assessment_v4"
    assert (
        pack.current() == "assessment_v4" and pack.load().rubric["synthetic"] is False
    )
    assert pack.load("assessment_v3").rubric["synthetic"] is True
    assert approval.Use.current("assessment").pack == "assessment_v4"


def test_practice_goal_has_its_own_approved_input_field():
    goal = "Practice testing streaming parsers"
    texts = snapshot._claim_texts({}, goal)
    assert texts[0][2] == goal and texts[0][-1] == ("submitted_fields.reason",)
    assert "submitted_fields.reason" in approval.FIELDS["assessment"]
    assert snapshot._claim_texts({}) == []


@pytest.mark.parametrize(
    "purpose,index", [("clarification_draft", 0), ("clarification_check", 1)]
)
def test_owner_approval_matches_the_actual_clarification_request(purpose, index):
    actual = clarify.uses(*clarify.packs_for())[index]
    assert approval.Use.current(purpose) == actual
    assert actual.purpose == purpose and actual.pack != pack.INTERPRET


@pytest.mark.parametrize("purpose", ["clarification_draft", "clarification_check"])
def test_owner_command_persists_and_revokes_each_clarification_approval(
    privileged_reset, purpose
):
    from assessments.models import ModelUseApproval
    from tests.test_live_safety import approve

    approve(purpose)
    record = ModelUseApproval.objects.filter(purpose=purpose).latest("id")
    actual = approval.Use.current(purpose)
    assert record.terms["pack"] == actual.pack
    assert record.terms["purpose"] == actual.purpose == purpose
    assert record.terms_sha256 == approval.digest(record.terms)
    approve(purpose, "--revoke")
    assert (
        ModelUseApproval.objects.filter(purpose=purpose).latest("id").action == "revoke"
    )
