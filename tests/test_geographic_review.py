"""Historical geographic matches require a human decision; never a provider call or automatic decline."""

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import Client
from django.urls import reverse

from applications import geographic_review
from applications.forms import AccessRequestForm
from applications.models import Application
from assessments import agent, decisions
from assessments.models import AssessmentInvocation, AssessmentRun, EvidenceItem
from assessments.services import Refused
from correspondence import processing
from correspondence.models import StaffItem
from tests.test_assessment import a, assessed, queued, valid  # noqa: F401
from tests.test_clarification import c  # noqa: F401
from tests.test_decision import d, decide  # noqa: F401
from tests.test_evidence import collect, ev  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_intake import RECEIVED, VALID, post
from tests.test_reference_receipt import ensure_receipt_templates, receipt_mode
from tests.test_outbound import p2, run_worker  # noqa: F401


def tripwire(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Geographic review must precede model construction")

    monkeypatch.setattr(agent, "build_model", refuse)


@pytest.mark.parametrize(
    "fields,outcome",
    [
        ({"residence_country": "IR"}, "hold"),
        ({"phone_country": "IR", "phone": "+982123456789"}, "admit"),
        (
            {
                "residence_country": "UA-43",
                "contribution": "A synthetic description of private work.",
            },
            "hold",
        ),
    ],
)
def test_geographic_match_preserves_contact_flow_and_requires_owner_decision(
    d, monkeypatch, settings, fields, outcome
):
    receipt_mode(settings, "separate")
    ensure_receipt_templates()
    tripwire(monkeypatch)
    app = collect(d, **fields)
    run_worker()
    app.refresh_from_db()
    assert app.contact_verified_at and app.stage == "assessing"
    assert not AssessmentRun.objects.filter(application=app).exists()
    assert not EvidenceItem.objects.filter(application=app).exists()
    item = StaffItem.objects.get(
        application=app, reason_code="sanctions_concern", status="open"
    )
    assert len(mail.outbox) == 2 and app.events.filter(kind="receipt_sent").count() == 1
    assert all("sanction" not in message.body.lower() for message in mail.outbox)
    received = Client().get(RECEIVED)
    assert received.status_code == 200 and b"sanctions_concern" not in received.content
    state = decisions.decision_state(app)
    assert state["human_only_code"] == "sanctions_concern" and state["run"] is None
    with pytest.raises(processing.Refused, match="resolution_not_allowed"):
        processing.resolve_exception(item.pk, "acknowledge", d.operator)
    with pytest.raises(PermissionDenied):
        decide(
            d,
            app,
            user=d.operator,
            human_only_reason="Reviewed the submitted geography.",
        )
    with pytest.raises(Refused, match="no_valid_assessment"):
        decide(d, app)
    client = Client()
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref]))
    assert page.status_code == 200 and b"Geographic review" in page.content
    result = decide(
        d,
        app,
        outcome,
        human_only_reason="Reviewed the submitted geography and recorded my decision.",
    )
    assert (
        result.human_only_code == "sanctions_concern" and result.basis == "human_only"
    )
    item.refresh_from_db()
    assert item.status == "resolved"
    assert Application.objects.get(pk=app.pk).stage == (
        "admitted" if outcome == "admit" else "on_hold"
    )
    assert result.decision_inputs["geographic_review"]["signals"]
    # A later unverified submission cannot lift the gate or reopen an already reviewed item.
    post(Client(), residence_country="GB")
    from assessments.runs import enqueue_assessment

    with transaction.atomic():
        Application.objects.select_for_update().get(pk=app.pk)
        assert enqueue_assessment(app, "staff_rerun") is None
    assert geographic_review.evidence(app)
    assert not StaffItem.objects.filter(
        application=app, reason_code="sanctions_concern", status="open"
    ).exists()


@pytest.mark.parametrize("region", ["UA-43", "UA-14", "UA-09", "UA-40"])
def test_geographic_regions_are_residence_choices_only(region):
    form = AccessRequestForm({**VALID, "residence_country": region})
    assert form.is_valid(), form.errors
    assert region not in dict(form.fields["phone_country"].choices)


@pytest.mark.parametrize(
    "country", ["CU", "IR", "KP", "SY", "UA-43", "UA-40", "UA-14", "UA-09"]
)
def test_geographic_residence_matches_are_review_signals(country):
    assert geographic_review.signals({"residence_country": country}) == [
        "residence_review"
    ]


@pytest.mark.parametrize(
    "prefix",
    [
        "53",
        "98",
        "850",
        "963",
        "7978",
        "7365",
        "7869",
        "7949",
        "7959",
        "38071",
        "38072",
        "38065",
        "38069",
    ],
)
def test_geographic_phone_prefix_matches_do_not_assert_residence(prefix):
    assert geographic_review.signals(
        {"phone_e164": "+" + prefix + "123456789", "residence_country": "GB"}
    ) == ["phone_prefix_review"]
    assert (
        geographic_review.signals(
            {"phone_e164": "+44" + prefix + "123456789", "residence_country": "GB"}
        )
        == []
    )


def test_geographic_gate_rechecks_queued_assessments_and_reply_admission(
    a, monkeypatch, settings
):
    app, run, seen = queued(a, monkeypatch, settings, valid())
    # A reviewed rule change must stop work queued before the new rule was installed.
    monkeypatch.setattr(
        geographic_review, "RESIDENCES", geographic_review.RESIDENCES | {"GB"}
    )
    tripwire(monkeypatch)
    run_worker()
    run.refresh_from_db()
    assert run.status == "refused" and run.error_code == "sanctions_concern"
    assert (
        seen["calls"] == 0 and not AssessmentInvocation.objects.filter(run=run).exists()
    )
    from assessments.interpret import Interpreter

    with transaction.atomic():
        Application.objects.select_for_update().get(pk=app.pk)
        assert Interpreter().admit(app) == "sanctions_concern"
    assert (
        StaffItem.objects.filter(
            application=app, reason_code="sanctions_concern"
        ).count()
        == 1
    )


def test_geographic_rule_change_invalidates_model_reliance_and_shown_decision(
    d, monkeypatch
):
    app, run, seen = assessed(d, monkeypatch, valid())
    assert (
        seen["calls"] == 1 and run.status == "succeeded"
    )  # nonmatching flow still works
    before = decisions.decision_state(app)
    monkeypatch.setattr(
        geographic_review, "RESIDENCES", geographic_review.RESIDENCES | {"GB"}
    )
    tripwire(monkeypatch)
    after = decisions.decision_state(app)
    assert after["digest"] != before["digest"] and after["run"] is None
    assert after["human_only_code"] == "sanctions_concern"
    with pytest.raises(Refused, match="changed_since_shown"):
        decide(d, app, expected_digest=before["digest"])
    with pytest.raises(Refused, match="no_valid_assessment"):
        decisions.record_routine_admit(
            app, run, rationale={}, verdict={}, actor="policy:synthetic"
        )
