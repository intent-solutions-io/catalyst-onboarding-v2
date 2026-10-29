"""9kg.85: the internal cohort's trial boundary, held in code (council record 033 Q2(b), Q5, Q6 and Q9; D-52).

In a live environment: no member is declined, every criterion is recorded unrated (capability unknown, evidence
strength none), and the required-details list must be empty (already refused there by config.guards). The reminder
quiet hours default to 02:00 to 13:00 UTC. A synthetic environment keeps the full decision surface, so the P3 tests
are unchanged.
"""

import pytest
from django.test import RequestFactory

import config.settings as project_settings
from assessments import decisions, staff_views
from assessments.models import QualificationDecision
from assessments.services import Refused
from config import guards
from tests.test_decision import d, decide, rationale, ready_app  # noqa: F401  (fixture chain and helpers)
from tests.test_decision import a, c, ev, p2, tls  # noqa: F401  (fixtures)

UNRATED = {"capability": "unknown", "evidence_strength": "none"}


def test_9kg_85_a_live_environment_refuses_every_cohort_decline_and_any_rated_criterion(d, monkeypatch, settings):
    app = ready_app(d, monkeypatch)
    settings.CATALYST_ENV = "production"
    assert decisions.cohort_boundary()
    with pytest.raises(Refused, match="decline_refused_in_the_internal_cohort"):
        decide(d, app, "decline", rationale=rationale("unknown", "none"))
    with pytest.raises(Refused, match="cohort_criteria_must_be_unrated"):
        decide(d, app, "admit", rationale=rationale())  # shown, moderate: a rating of a colleague
    one_rated = rationale("unknown", "none")
    first = next(iter(one_rated))
    one_rated[first] = {**one_rated[first], "capability": "not_shown", "evidence_strength": "weak"}
    with pytest.raises(Refused, match="cohort_criteria_must_be_unrated"):
        decide(d, app, "hold", rationale=one_rated)  # every outcome, not only an admit
    assert not QualificationDecision.objects.filter(application=app).exists()
    admitted = decide(d, app, "admit", rationale=rationale("unknown", "none"))
    assert admitted.outcome == "admit"
    assert all({k: v for k, v in entry.items() if k != "note"} == UNRATED for entry in admitted.rationale.values())


def test_9kg_85_the_decision_form_offers_no_decline_and_no_rating_in_a_live_environment(d, monkeypatch, settings):
    app = ready_app(d, monkeypatch)
    request = RequestFactory().get("/")
    request.user = d.decider
    synthetic = staff_views._decision_context(request, app)
    assert "decline" in synthetic["outcomes"] and synthetic["capability"] == decisions.CAPABILITY
    settings.CATALYST_ENV = "production"
    live = staff_views._decision_context(request, app)
    assert "decline" not in live["outcomes"] and "admit" in live["outcomes"] and live["cohort_boundary"] is True
    assert (live["capability"], live["strength"]) == (("unknown",), ("none",))
    monkeypatch.setattr(decisions, "COHORT_BOUNDARY", False)  # lifted by a reviewed release before wider enrollment
    assert not decisions.cohort_boundary() and "decline" in staff_views._decision_context(request, app)["outcomes"]


def test_9kg_85_a_live_environment_refuses_required_details_and_the_quiet_hours_default_to_the_cohort_night():
    def problems(environment, details):
        holder = type("S", (), {"CATALYST_ENV": environment, "CATALYST_AGREEMENT_REQUIRED_DETAILS": details})
        return [p for p in guards.agreement_problems(holder, {}) if "REQUIRED_DETAILS" in p]

    # Already held by 021 section 10 (synthetic agreements only): 033 Q2(b) needs no new guard, only this proof.
    assert problems("production", {"nda": ["synthetic_field"]}) == [
        "CATALYST_AGREEMENT_REQUIRED_DETAILS is allowed only in the test and staging environments (synthetic agreements only)"]
    assert problems("production", {}) == [] and problems("test", {"nda": ["synthetic_field"]}) == []
    assert (project_settings.CATALYST_REMINDER_QUIET_START_HOUR, project_settings.CATALYST_REMINDER_QUIET_END_HOUR) == (2, 13)
