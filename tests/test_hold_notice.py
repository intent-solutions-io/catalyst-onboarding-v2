"""bgl.24 (D-55): the still-in-review note of a hold, and the owner-approved decline wording.

A recorded hold queues one `send_hold_notice`, due ten business days later, only while CATALYST_HOLD_NOTICE_ENABLED is
on (off by default); it freezes the note from the `hold_notice` template and hands it to the P2 sender, at most once per
application. The decline notice keeps its own path (tests/test_decline_notice.py); here its new real wording is added by
`catalyst_seed_wording`, approved by the owner, and greets by first name only.

The reset truncates every correspondence table, so a test seeds the templates from their migrations when it needs them.
Everything is synthetic: the scripted SMTP server on loopback and `example.test` addresses.
"""

import json
from datetime import UTC, datetime
from importlib import import_module
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db.models.functions import Now

from applications import notices
from applications.models import Application
from assessments import hold
from assessments.hold import SendHoldNotice
from config import guards, post_restore
from config.system_health import decision_health
from correspondence import outbound, wording
from correspondence.models import (
    ApprovedMessage,
    MessageTemplate,
    MessageTemplateVersion,
    StaffItem,
)
from correspondence.rendering import canonical_digest
from tests.test_assessment import a  # noqa: F401  (fixture chain)
from tests.test_clarification import c  # noqa: F401
from tests.test_decision import d, decide, ready_app  # noqa: F401
from tests.test_decline_notice import (
    declined,
    notices_of as decline_notices_of,
    run_decline_only,
    template_owner,
)
from tests.test_decline_notice import ensure_template as ensure_decline_template
from tests.test_evidence import ev  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_invitation import ensure_notice_templates
from tests.test_outbound import p2, run_worker  # noqa: F401
from tests.test_verification_wording import (
    ensure_template as ensure_verification_template,
)
from workflow import business_days, ledger
from workflow.models import PendingAction

MIGRATION = import_module("correspondence.migrations.0027_hold_notice")


@pytest.fixture
def h(d, settings):
    settings.CATALYST_REMINDER_QUIET_START_HOUR = (
        settings.CATALYST_REMINDER_QUIET_END_HOUR
    ) = 0  # no quiet hours here
    return d


def ensure_hold_template():
    if not MessageTemplate.objects.filter(key=MIGRATION.KEY).exists():
        MIGRATION.create_template(MessageTemplate, MessageTemplateVersion)
    return MessageTemplateVersion.objects.get(template__key=MIGRATION.KEY, version=1)


def held(env, monkeypatch):
    ensure_hold_template()
    app = ready_app(env, monkeypatch)
    decision = decide(env, app, "hold")
    return Application.objects.get(pk=app.pk), decision


def hold_actions(app):
    return list(
        PendingAction.objects.filter(kind="send_hold_notice", subject_id=app.public_ref)
    )


def notes_of(app):
    return list(ApprovedMessage.objects.filter(application=app, kind="hold_notice"))


def run_hold_only():
    """One `send_hold_notice` claim without the worker command (which needs the effect journal outside test)."""
    return ledger.run_one({"send_hold_notice": SendHoldNotice()})


def due_now(app):
    PendingAction.objects.filter(
        kind="send_hold_notice", subject_id=app.public_ref, status="queued"
    ).update(due_at=Now())


def real_hold_version(env):
    subject, body, variables = wording.REAL["hold_notice"]
    template = ensure_hold_template().template
    version = MessageTemplateVersion.objects.create(
        template=template,
        version=2,
        subject=subject,
        body_text=body,
        variables=variables,
        content_sha256=canonical_digest(subject, body),
        synthetic=False,
    )
    return outbound.approve_template_version(
        version.pk, template_owner(env, "hold-owner")
    )


# --- the switch ------------------------------------------------------------------------------------------------------


def test_bgl24_with_the_switch_off_a_hold_queues_nothing_and_a_queued_note_is_cancelled_unsent(
    h, monkeypatch, settings
):
    assert settings.CATALYST_HOLD_NOTICE_ENABLED is False  # the shipped default
    app, decision = held(h, monkeypatch)
    assert app.stage == "on_hold" and hold_actions(app) == []
    assert hold.schedule(app, decision) is None
    before = len(h.server.messages)
    run_worker()
    assert notes_of(app) == [] and len(h.server.messages) == before
    # Queued while on, then switched off before it ran: cancelled, nothing frozen, nothing sent.
    settings.CATALYST_HOLD_NOTICE_ENABLED = True
    monkeypatch.setattr(hold, "BUSINESS_DAYS", 0)
    action = hold.schedule(app, decision)
    settings.CATALYST_HOLD_NOTICE_ENABLED = False
    run_worker()
    action.refresh_from_db()
    assert (action.status, action.last_error) == ("cancelled", "hold_notice_disabled")
    assert notes_of(app) == [] and len(h.server.messages) == before


def test_bgl24_the_switch_accepts_only_true_or_false():
    shipped = SimpleNamespace(CATALYST_QUALIFICATION_AUTHORITY=None)
    problem = "CATALYST_HOLD_NOTICE_ENABLED must be true or false"
    for typo in ("on", "True", "1", ""):
        assert problem in guards.decision_problems(
            shipped, {"CATALYST_HOLD_NOTICE_ENABLED": typo}
        ), typo
    for value in ("true", "false"):
        assert (
            guards.decision_problems(shipped, {"CATALYST_HOLD_NOTICE_ENABLED": value})
            == []
        )
    assert guards.decision_problems(shipped, {}) == []  # unset is off


# --- one note, once ----------------------------------------------------------------------------------------------------


def test_bgl24_with_the_switch_on_a_hold_sends_exactly_one_note_through_the_p2_sender_and_never_a_second(
    h, monkeypatch, settings
):
    settings.CATALYST_HOLD_NOTICE_ENABLED = True
    monkeypatch.setattr(
        hold, "BUSINESS_DAYS", 0
    )  # due at once; the business-day timer has its own test
    app, decision = held(h, monkeypatch)
    [action] = hold_actions(app)
    assert (action.status, action.idempotency_key, action.input_ref) == (
        "queued",
        f"send_hold_notice:{app.public_ref}",
        str(decision.public_id),
    )
    before = len(h.server.messages)
    run_worker()
    [message] = notes_of(app)
    action.refresh_from_db()
    message.refresh_from_db()
    assert action.status == "done" and message.disposition == "accepted_by_server"
    assert (
        message.authority == "system_policy"
        and message.template_version.template.key == "hold_notice"
    )
    assert len(h.server.messages) == before + 1
    wire = h.server.parsed()
    assert wire["Subject"] == MIGRATION.SUBJECT
    body = wire.get_content()
    assert body.startswith(
        notices.DRAFT_MARKER
    )  # the test environment sends the unapproved draft, marked
    assert "Hello Ada," in body and app.display_name not in body  # first name only
    assert app.events.get(kind="hold_notice_queued").data["decision"] == str(
        decision.public_id
    )
    # Never twice: another pass, a redelivered action and a second scheduling attempt add nothing.
    run_worker()
    PendingAction.objects.filter(pk=action.pk).update(
        status="queued", due_at=Now(), completed_at=None
    )
    run_worker()
    action.refresh_from_db()
    assert (action.status, action.last_error) == ("done", "already_queued")
    assert hold.schedule(app, decision) is None and len(hold_actions(app)) == 1
    assert len(notes_of(app)) == 1 and len(h.server.messages) == before + 1


def test_bgl24_a_decision_off_the_hold_before_the_note_is_due_cancels_it(
    h, monkeypatch, settings
):
    settings.CATALYST_HOLD_NOTICE_ENABLED = True
    app, _ = held(h, monkeypatch)
    decide(h, app, "admit")  # the staff path back from a hold (9kg.50)
    due_now(app)
    assert run_hold_only()
    [action] = hold_actions(app)
    assert (action.status, action.last_error) == (
        "cancelled",
        "application_not_on_hold",
    ) and notes_of(app) == []


# --- the timer -------------------------------------------------------------------------------------------------------


def test_bgl24_the_note_is_due_ten_business_days_after_the_hold_and_waits_if_run_early(
    h, monkeypatch, settings
):
    # Monday to Friday by the UTC date: from a Friday afternoon, two weekends pass; calendar days would say Monday 16.
    assert hold.due(datetime(2026, 11, 6, 15, 30, tzinfo=UTC)) == datetime(
        2026, 11, 20, tzinfo=UTC
    )
    assert hold.due(datetime(2026, 11, 5, 23, 59, tzinfo=UTC)) == datetime(
        2026, 11, 19, tzinfo=UTC
    )
    assert hold.due(datetime(2026, 11, 7, 9, 0, tzinfo=UTC)) == datetime(
        2026, 11, 20, tzinfo=UTC
    )  # a Saturday hold
    settings.CATALYST_HOLD_NOTICE_ENABLED = True
    app, decision = held(h, monkeypatch)
    [action] = hold_actions(app)
    assert action.due_at == hold.due(decision.created_at)
    assert (
        business_days.business_days_between(decision.created_at, action.due_at)
        == hold.BUSINESS_DAYS
        == 10
    )
    run_worker()  # not due: nothing runs
    action.refresh_from_db()
    assert action.status == "queued" and action.attempts == 0 and notes_of(app) == []
    # Released early by hand (or redelivered): it waits for the tenth business day again, freezing nothing.
    due_now(app)
    assert run_hold_only()
    action.refresh_from_db()
    assert (action.status, action.last_error, action.attempts) == (
        "queued",
        "not_yet_due",
        0,
    )
    assert (
        abs((action.due_at - hold.due(decision.created_at)).total_seconds()) < 1
        and notes_of(app) == []
    )


def test_bgl24_quiet_hours_hold_a_due_note(h, monkeypatch, settings):
    settings.CATALYST_HOLD_NOTICE_ENABLED = True
    monkeypatch.setattr(hold, "BUSINESS_DAYS", 0)
    app, _ = held(h, monkeypatch)
    hour = business_days.db_now().hour
    (
        settings.CATALYST_REMINDER_QUIET_START_HOUR,
        settings.CATALYST_REMINDER_QUIET_END_HOUR,
    ) = hour, (hour + 1) % 24
    assert run_hold_only()
    [action] = hold_actions(app)
    assert (action.status, action.last_error, action.attempts) == (
        "queued",
        "quiet_hours",
        0,
    ) and notes_of(app) == []


# --- the wording: refused live until the owner approves a real version ----------------------------------------------


def test_bgl24_the_note_waits_with_one_staff_item_until_the_owner_approves_real_wording_and_health_names_it(
    h, monkeypatch, settings
):
    settings.CATALYST_HOLD_NOTICE_ENABLED = True
    monkeypatch.setattr(hold, "BUSINESS_DAYS", 0)
    app, _ = held(h, monkeypatch)
    settings.CATALYST_ENV = "production"
    assert "hold_notice_unapproved" in decision_health()["anomalies"]
    assert run_hold_only()
    [action] = hold_actions(app)
    assert (action.status, action.last_error, action.attempts) == (
        "queued",
        "hold_notice_not_approved",
        0,
    )
    [item] = StaffItem.objects.filter(
        application=app, reason_code="hold_notice_refused", status="open"
    )
    assert notes_of(app) == []
    real = real_hold_version(h)
    report = decision_health()
    assert (
        "hold_notice_unapproved" not in report["anomalies"]
        and report["hold_notice_enabled"] is True
    )
    assert set(report["hold_notice"]) == {
        "status",
        "version",
        "sha256",
        "synthetic",
    }  # never the wording
    due_now(app)
    assert run_hold_only()
    action.refresh_from_db()
    [message] = notes_of(app)
    assert action.status == "done" and message.template_version_id == real.pk
    assert (
        message.frozen_subject
        == "Your Intent Solutions access request: still in review"
    )
    assert message.frozen_body == (
        "Hello Ada,\n\nYour request is still in review; no action is needed from you. We will write when there is a "
        "decision. If you have a question, reply to this email.\n"
    )  # no draft marker, first name only
    item.refresh_from_db()
    assert (
        item.status == "resolved"
        and item.resolution.resolution_code == "hold_notice_queued"
    )
    MessageTemplateVersion.objects.filter(pk=real.pk).update(status="retired")
    settings.CATALYST_HOLD_NOTICE_ENABLED = False
    assert (
        "hold_notice_unapproved" not in decision_health()["anomalies"]
    )  # off: nothing can wait on the wording


def test_bgl24_a_note_copy_under_review_after_a_restore_defers_the_freeze(
    h, monkeypatch, settings
):
    from correspondence.staff_items import open_item

    settings.CATALYST_HOLD_NOTICE_ENABLED = True
    monkeypatch.setattr(hold, "BUSINESS_DAYS", 0)
    app, _ = held(h, monkeypatch)
    item = open_item(
        "restore_effect_unknown_send", "sent:synthetic-hold", application=app
    )
    assert run_hold_only()
    [action] = hold_actions(app)
    assert (action.status, action.last_error) == (
        "queued",
        "sent_after_backup_pending_review",
    ) and notes_of(app) == []
    StaffItem.objects.filter(pk=item.pk).update(status="resolved")
    due_now(app)
    assert run_hold_only()
    assert len(notes_of(app)) == 1


def test_bgl24_the_handler_is_registered_redeliverable_and_automated():
    handler = ledger.handlers()["send_hold_notice"]
    assert (
        isinstance(handler, SendHoldNotice)
        and handler.redeliverable
        and handler.automated
    )
    assert (
        "send_hold_notice" not in post_restore.outward_kinds()
    )  # a timer that freezes nothing until due, as the lapse


# --- the decline wording (D-55) ----------------------------------------------------------------------------------------


def test_d55_the_approved_decline_wording_greets_by_first_name_only_and_clears_the_health_anomaly(
    h, monkeypatch, settings
):
    ensure_notice_templates()
    ensure_verification_template()
    ensure_decline_template()
    ensure_hold_template()
    out = StringIO()
    call_command("catalyst_seed_wording", stdout=out)
    seeded = json.loads(out.getvalue())
    assert seeded["decline_notice"]["added"] and seeded["hold_notice"]["added"]
    version = MessageTemplateVersion.objects.get(
        template__key="decline_notice", version=seeded["decline_notice"]["version"]
    )
    assert (version.status, version.synthetic, version.variables, version.subject) == (
        "draft",
        False,
        ["first_name"],
        "Your Intent Solutions access request",
    )
    settings.CATALYST_ENV = "production"
    assert (
        "decline_notice_unapproved" in decision_health()["anomalies"]
    )  # a draft is never served live
    outbound.approve_template_version(
        version.pk,
        template_owner(h, "d55-owner"),
        expected_digest=version.content_sha256,
    )
    assert "decline_notice_unapproved" not in decision_health()["anomalies"]
    rendered = notices.wording(
        "decline_notice", {"display_name": "Ada Example Lovelace"}
    )
    assert rendered.approved and rendered.text.startswith("Hello Ada,\n\n")
    assert "Example" not in rendered.text and "Lovelace" not in rendered.text
    # Recorded where a decline may be, then frozen where only approved real wording is served.
    settings.CATALYST_ENV = "test"
    app, _ = declined(h, monkeypatch)
    settings.CATALYST_ENV = "production"
    assert run_decline_only()
    [message] = decline_notices_of(app)
    assert message.frozen_subject == "Your Intent Solutions access request"
    assert message.frozen_body == (
        "Hello Ada,\n\nThanks for your request to join the Intent Solutions practitioner community. We are not able to "
        "advance it right now. We keep requests on file for twelve months and then delete them; if anything changes on "
        "your side, reply to this email. Our privacy and data-retention notices are at intentsolutions.io/privacy/ and "
        "intentsolutions.io/data-retention/.\n"
    )
    assert (
        app.display_name not in message.frozen_body
        and notices.DRAFT_MARKER not in message.frozen_body
    )
