"""oc4.11 (029 sections 5.2 and 17.3; 016 section 10.19): the decline notice.

A recorded decline queues one `send_decline`, which freezes the notice from the `decline_notice` template and hands it
to the P2 sender; `declined` is terminal, so the send check lets exactly this kind through. Uncertainty and failure
reach the usual staff items and decisions; a permanent bounce opens "not notified" before the closed-application
exception; withholding is a recorded choice of the decision-maker; the wording is refused in a live environment until
the owner approves a real version (the PR #91 pattern). No reason, rationale or model output is ever sent.

The reset truncates every correspondence table, so a test seeds the template from migration 0019 when it needs it.
Everything is synthetic: the scripted SMTP and IMAP servers on loopback and `example.test` addresses.
"""

from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import PermissionDenied
from django.db.models.functions import Now
from django.test import Client
from django.urls import reverse

from applications import notices
from applications.models import Application
from assessments import decisions
from assessments.decline import SendDecline
from assessments.models import QualificationDecision
from assessments.services import Refused
from config.system_health import decision_health
from correspondence import inbound, outbound, staff_actions
from correspondence.models import ApprovedMessage, MessageTemplate, MessageTemplateVersion, OutboundMessage, StaffItem
from correspondence.rendering import canonical_digest
from correspondence.roles import DECISION_MAKER, TEMPLATE_OWNER
from tests.imap_server import ScriptedIMAP
from tests.smtp_server import ScriptedSMTP
from tests.test_assessment import a  # noqa: F401  (fixture chain)
from tests.test_clarification import c  # noqa: F401
from tests.test_decision import d, decide, rationale, ready_app  # noqa: F401
from tests.test_evidence import ev  # noqa: F401
from tests.test_inbound import TRUSTED, collect, tls  # noqa: F401
from tests.test_intake_notice import LABEL_A, on_file
from tests.test_outbound import p2, run_worker, staff  # noqa: F401
from tests.test_processing import bounce
from workflow import ledger
from workflow.models import PendingAction

MIGRATION = import_module("correspondence.migrations.0019_decline_notice")
SECRET_NOTE = "SYNTHETIC-RATIONALE-MARKER weak portfolio"
SECRET_REASON = "SYNTHETIC-REASON-TEXT-MARKER"
SECRET_CODE = "synthetic_secret_code"


def ensure_template():
    if not MessageTemplate.objects.filter(key=MIGRATION.DECLINE_KEY).exists():
        MIGRATION.create_template(MessageTemplate, MessageTemplateVersion)
    return MessageTemplateVersion.objects.get(template__key=MIGRATION.DECLINE_KEY, version=1)


def template_owner(env, name="decline-template-owner"):
    return staff(env, name, TEMPLATE_OWNER)


def real_version(env, version=2, body="Hello $display_name,\n\nReal approved wording, version two.\n", synthetic=False):
    old = ensure_template()
    new = MessageTemplateVersion.objects.create(
        template=old.template, version=version, subject=old.subject, body_text=body, variables=["display_name"],
        content_sha256=canonical_digest(old.subject, body), synthetic=synthetic)
    return outbound.approve_template_version(new.pk, template_owner(env, f"decline-owner-v{version}"))


def declined(env, monkeypatch, **kw):
    ensure_template()
    app = ready_app(env, monkeypatch)
    notes = {criterion: {**value, "note": SECRET_NOTE} for criterion, value in rationale().items()}
    decision = decide(env, app, "decline", reason_code=SECRET_CODE, reason_text=SECRET_REASON, rationale=notes, **kw)
    return Application.objects.get(pk=app.pk), decision


def notices_of(app):
    return list(ApprovedMessage.objects.filter(application=app, kind="decline"))


def decline_actions(app):
    return list(PendingAction.objects.filter(kind="send_decline", subject_id=app.public_ref))


def sends_of(message):
    return list(PendingAction.objects.filter(kind="send_message", input_ref=str(message.send_ref)).order_by("id"))


def run_decline_only():
    """One `send_decline` claim without the worker command (which needs the effect journal outside test)."""
    return ledger.run_one({"send_decline": SendDecline()})


def due_now(app):
    PendingAction.objects.filter(kind="send_decline", subject_id=app.public_ref, status="queued").update(due_at=Now())


# --- one notice, from the template, through the P2 sender ----------------------------------------------------------

def test_oc4_11_a_decline_sends_exactly_one_notice_from_the_template_through_the_p2_sender(d, monkeypatch):
    app, decision = declined(d, monkeypatch)
    before = len(d.server.messages)
    [action] = decline_actions(app)
    assert (action.status, action.idempotency_key, action.input_ref) == ("queued", f"send_decline:{app.public_ref}",
                                                                         str(decision.public_id))
    assert decision.decision_inputs["decline_notice"] == {"choice": "send"}
    run_worker()
    [message] = notices_of(app)
    action.refresh_from_db()
    message.refresh_from_db()
    assert action.status == "done" and message.disposition == "accepted_by_server"
    assert message.authority == "system_policy" and message.template_version.template.key == "decline_notice"
    assert [a.status for a in sends_of(message)] == ["done"]
    assert len(d.server.messages) == before + 1  # exactly one notice left
    wire = d.server.parsed()
    assert wire["Subject"] == MIGRATION.DECLINE_SUBJECT and wire["Message-ID"] == outbound.message_id(message.send_ref)
    body = wire.get_content()
    assert body.startswith(notices.DRAFT_MARKER)  # the test environment sends the unapproved draft, marked
    assert f"Hello {app.display_name}," in body and "[counsel to state" in body
    event = app.events.get(kind="decline_notice_queued")
    assert event.data["decision"] == str(decision.public_id) and event.data["draft"] is True
    # Exactly one, however often it runs: a second pass sends nothing, and a redelivered action freezes nothing new.
    run_worker()
    PendingAction.objects.filter(pk=action.pk).update(status="queued", due_at=Now(), completed_at=None)
    run_worker()
    action.refresh_from_db()
    assert action.status == "done" and action.last_error == "already_queued"
    assert len(notices_of(app)) == 1 and len(d.server.messages) == before + 1


def test_oc4_11_the_notice_carries_no_reason_rationale_or_model_output(d, monkeypatch):
    seen = []
    real = notices.wording

    def spy(key, values=None):
        seen.append((key, dict(values or {})))
        return real(key, values)
    monkeypatch.setattr(notices, "wording", spy)
    app, decision = declined(d, monkeypatch)
    run_worker()
    [message] = notices_of(app)
    # The only value the decline notice ever renders (the verification mail renders its link, 9kg.80; not this notice).
    assert [s for s in seen if s[0] == "decline_notice"] == [("decline_notice", {"display_name": app.display_name})]
    assert {key for key, _ in seen} <= {"decline_notice", "verification_invitation"}
    wire = d.server.messages[-1]["data"].decode()
    run = decision.run
    leaks = [SECRET_NOTE, SECRET_REASON, SECRET_CODE, decision.policy_ref, str(decision.public_id), "rationale"]
    leaks += [run.recommendation_basis] if run is not None and getattr(run, "recommendation_basis", "") else []
    for text in (message.frozen_subject, message.frozen_body, wire):
        for leak in leaks:
            assert leak not in text, leak
    version = MessageTemplateVersion.objects.get(template__key="decline_notice", version=1)
    assert version.variables == ["display_name"] and version.synthetic and version.status == "draft"
    assert "$" not in version.body_text.replace("$display_name", "")
    for claim in ("guarantee", "promise", "legal", "right to", "will be deleted", "model", "automated"):
        assert claim not in MIGRATION.DECLINE_BODY.lower(), claim  # a placeholder makes no promise or claim


# --- the send check: the one exception to "nothing is sent to a closed application" ----------------------------------

def test_oc4_11_only_the_decline_kind_reaches_a_declined_application_and_nothing_reaches_another_closed_stage():
    def case(kind, stage):
        return outbound.declined_notice(SimpleNamespace(kind=kind), SimpleNamespace(stage=stage))
    assert case("decline", "declined")
    for kind, stage in (("question", "declined"), ("reminder", "declined"), ("staff_message", "declined"),
                        ("welcome", "declined"), ("decline", "withdrawn"), ("decline", "closed")):
        assert not case(kind, stage), (kind, stage)


# --- uncertain, failed, bounced ------------------------------------------------------------------------------------

def test_oc4_11_an_uncertain_notice_goes_to_staff_and_a_resend_reaches_the_declined_applicant_once(d, monkeypatch):
    d.use(ScriptedSMTP({"end": ["silent", 250]}))  # the first exchange gets no reply; the resend is accepted
    app, _ = declined(d, monkeypatch)
    run_worker()
    [message] = notices_of(app)
    message.refresh_from_db()
    assert message.disposition == "active"
    assert list(OutboundMessage.objects.filter(approved_message=message).values_list("status", flat=True)) == ["unknown"]
    assert [a.status for a in sends_of(message)] == ["uncertain"]  # never an ordinary retry
    assert set(StaffItem.objects.filter(approved_message=message).values_list("reason_code", flat=True)) == {"send_outcome_unknown"}
    decider = staff(d, "decline-decider", DECISION_MAKER)
    staff_actions.decide_uncertain_send(message.pk, decider, "authorize_resend", note="synthetic resend")
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "accepted_by_server" and [a.status for a in sends_of(message)] == ["uncertain", "done"]
    assert len(d.server.messages) == 2 and d.server.parsed(0)["Message-ID"] == d.server.parsed(1)["Message-ID"]


def test_oc4_11_a_permanently_rejected_notice_goes_to_staff_and_is_abandoned_never_revised(d, monkeypatch):
    d.use(ScriptedSMTP({"rcpt": 550}))
    app, _ = declined(d, monkeypatch)
    run_worker()
    [message] = notices_of(app)
    message.refresh_from_db()
    assert message.disposition == "rejected_permanent" and [a.status for a in sends_of(message)] == ["failed"]
    assert list(StaffItem.objects.filter(approved_message=message).values_list("reason_code", flat=True)) == ["send_rejected_permanent"]
    decider = staff(d, "decline-decider", DECISION_MAKER)
    with pytest.raises(outbound.Refused, match="revision_not_supported_for_this_kind"):
        staff_actions.decide_uncertain_send(message.pk, decider, "revise")
    staff_actions.decide_uncertain_send(message.pk, decider, "abandon", note="synthetic: told another way")
    message.refresh_from_db()
    assert message.disposition == "operator_abandoned" and d.server.messages == []


@pytest.fixture
def dm(d, tls, settings):  # noqa: F811
    """`d` plus the TLS IMAP server and the bootstrapped cursor of tests/test_inbound.py's `mailbox`."""
    imap = ScriptedIMAP(tls=tls.good).start()
    settings.CATALYST_MAIL_CA_FILE = tls.ca
    settings.CATALYST_MAIL_IMAP_PORT = imap.port
    settings.CATALYST_MAIL_TRUSTED_AUTHSERV_ID = TRUSTED
    settings.CATALYST_MAIL_MAILBOX_REF = "applicants"
    settings.CATALYST_MAIL_COLLECT_FOLDER = "INBOX"
    settings.CATALYST_MAIL_SENT_FOLDER = ""
    settings.CATALYST_MAIL_POLL_SECONDS = 3600
    settings.CATALYST_MAIL_COLLECT_FAILURE_LIMIT = 3
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    d.imap = imap
    d.cursor = inbound.bootstrap_mailbox("from_now")
    yield d
    imap.stop()


def test_oc4_11_a_permanent_bounce_of_the_notice_opens_not_notified_before_the_closed_application_exception(dm, monkeypatch):
    app, _ = declined(dm, monkeypatch)
    run_worker()
    [message] = notices_of(app)
    message.refresh_from_db()
    assert message.disposition == "accepted_by_server"
    dm.imap.deliver(bounce(message, status="5.1.1"))
    collect()
    items = list(StaffItem.objects.filter(application=app).order_by("id").values_list("reason_code", "approved_message_id"))
    assert items == [("decline_not_notified", message.pk), ("application_closed", None)]  # "not notified" comes first
    [item] = StaffItem.objects.filter(reason_code="decline_not_notified")
    assert item.dedupe_key == f"decline:{message.send_ref}" and item.status == "open"
    # The decision-maker settles it with a note; an operator may not (the reason-to-permission table).
    from correspondence import processing
    from correspondence.roles import OPERATOR

    with pytest.raises(PermissionDenied):
        processing.resolve_exception(item.pk, "acknowledge", staff(dm, "decline-operator", OPERATOR))
    processing.resolve_exception(item.pk, "acknowledge", staff(dm, "decline-decider", DECISION_MAKER), note="told by phone")
    item.refresh_from_db()
    assert item.status == "resolved"


def test_oc4_11_a_delayed_report_is_not_a_failure_and_gets_only_the_closed_application_exception(dm, monkeypatch):
    app, _ = declined(dm, monkeypatch)
    run_worker()
    [message] = notices_of(app)
    dm.imap.deliver(bounce(message, status="4.4.1"))
    collect()
    assert list(StaffItem.objects.filter(application=app).values_list("reason_code", flat=True)) == ["application_closed"]


def test_oc4_11_a_report_with_no_status_is_a_possible_failure_and_opens_not_notified(dm, monkeypatch):
    app, _ = declined(dm, monkeypatch)
    run_worker()
    [message] = notices_of(app)
    report = bounce(message, status="5.1.1").replace(b"Status: 5.1.1\r\n", b"")
    assert b"Status:" not in report
    dm.imap.deliver(report)
    collect()
    items = list(StaffItem.objects.filter(application=app).order_by("id").values_list("reason_code", flat=True))
    assert items == ["decline_not_notified", "application_closed"]


# --- withheld -------------------------------------------------------------------------------------------------------

def test_oc4_11_withholding_is_a_recorded_decision_maker_choice_and_sends_nothing(d, monkeypatch):
    ensure_template()
    app = ready_app(d, monkeypatch)
    for kw, code in (({"decline_notice": "withhold"}, "withhold_reason_needed"),
                     ({"decline_notice": "withhold", "withhold_reason": "short"}, "withhold_reason_needed"),
                     ({"decline_notice": "maybe"}, "decline_notice_choice_invalid"),
                     ({"decline_notice": "send", "withhold_reason": "Reason without withholding."},
                      "withhold_reason_only_when_withholding")):
        with pytest.raises(Refused, match=code):
            decide(d, app, "decline", **kw)
    with pytest.raises(Refused, match="decline_notice_choice_only_for_decline"):
        decide(d, app, "hold", decline_notice="withhold", withhold_reason="Synthetic: not applicable to a hold.")
    assert not QualificationDecision.objects.filter(application=app).exists()
    before = len(d.server.messages)
    decision = decide(d, app, "decline", decline_notice="withhold", withhold_reason="Synthetic: told in person at the review.")
    assert decision.decision_inputs["decline_notice"] == {"choice": "withhold",
                                                          "reason": "Synthetic: told in person at the review."}
    event = Application.objects.get(pk=app.pk).events.get(kind="decline_notice_withheld")
    assert event.actor_type == "staff" and event.actor_ref == f"user:{d.decider.pk}"
    assert event.data == {"decision": str(decision.public_id), "reason": "Synthetic: told in person at the review."}
    assert decline_actions(app) == []  # nothing is queued
    run_worker()
    assert notices_of(app) == [] and len(d.server.messages) == before


def test_oc4_11_the_decision_form_offers_the_choice_and_records_a_withheld_notice(d, monkeypatch):
    ensure_template()
    app = ready_app(d, monkeypatch)
    client = Client()
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    assert '<input type="checkbox" name="decline_notice" value="withhold"> Withhold the decline notice' in page
    assert "never carries your reasoning" in page and "checked" not in page  # sending is the default; nothing preselected
    form = {"digest": decisions.decision_state(app)["digest"], "outcome": "decline", "reason_code": "synthetic_reason",
            "decline_notice": "withhold", "withhold_reason": ""}
    for criterion, values in rationale().items():
        form.update({f"cap-{criterion}": values["capability"], f"str-{criterion}": values["evidence_strength"],
                     f"note-{criterion}": values["note"]})
    url_ = reverse("assessments_staff:decide", args=[app.public_ref])
    refused = client.post(url_, form)
    assert refused.status_code == 409 and "Refused: withhold_reason_needed" in refused.content.decode()
    assert "checked" not in refused.content.decode()  # the withhold choice is never carried over, like the outcome
    form["withhold_reason"] = "Synthetic: the applicant asked not to be emailed."
    assert client.post(url_, form).status_code == 302
    decision = QualificationDecision.objects.get(application=app)
    assert decision.decision_inputs["decline_notice"]["choice"] == "withhold" and decline_actions(app) == []


# --- the wording: the PR #91 pattern ---------------------------------------------------------------------------------

def test_oc4_11_unapproved_or_synthetic_wording_is_refused_in_a_live_environment_until_a_real_version_is_approved(d, monkeypatch, settings):
    app, _ = declined(d, monkeypatch)
    settings.CATALYST_ENV = "production"
    assert run_decline_only()
    [action] = decline_actions(app)
    assert (action.status, action.last_error, action.attempts) == ("queued", "decline_notice_not_approved", 0)
    [item] = StaffItem.objects.filter(application=app, reason_code="decline_notice_refused", status="open")
    assert notices_of(app) == []
    outbound.approve_template_version(ensure_template().pk, template_owner(d))  # approved, but still the placeholder
    due_now(app)
    assert run_decline_only()
    action.refresh_from_db()
    assert action.status == "queued" and action.last_error == "decline_notice_synthetic" and notices_of(app) == []
    assert StaffItem.objects.filter(application=app, reason_code="decline_notice_refused").count() == 1  # one item, not one per look
    real = real_version(d)
    due_now(app)
    assert run_decline_only()
    action.refresh_from_db()
    [message] = notices_of(app)
    assert action.status == "done" and message.template_version_id == real.pk
    assert message.frozen_body == f"Hello {app.display_name},\n\nReal approved wording, version two.\n"  # no marker
    assert app.events.get(kind="decline_notice_queued").data["draft"] is False
    item.refresh_from_db()
    assert item.status == "resolved" and item.resolution.resolution_code == "decline_notice_queued"
    settings.CATALYST_ENV = "test"
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "accepted_by_server"


def test_oc4_11_the_health_report_names_unusable_decline_wording_once_decisions_can_be_recorded(d, settings):
    assert decision_health()["anomalies"] == ["decline_notice_unapproved"]  # the authority is set; no template at all
    ensure_template()
    report = decision_health()
    assert report["anomalies"] == [] and report["decline_notice"]["status"] == "draft"  # a marked draft may be sent here
    assert set(report["decline_notice"]) == {"status", "version", "sha256", "synthetic"}  # never the wording
    settings.CATALYST_ENV = "production"
    assert decision_health()["anomalies"] == ["decline_notice_unapproved"]
    real_version(d)
    assert decision_health()["anomalies"] == []
    settings.CATALYST_QUALIFICATION_AUTHORITY = None
    MessageTemplateVersion.objects.filter(template__key="decline_notice", version=2).update(status="retired")
    assert decision_health()["anomalies"] == []  # no decision can be recorded, so nothing waits on the wording


# --- refusals: before the handler, a member on file, a restore under review ------------------------------------------

def test_oc4_11_a_held_send_decline_from_before_the_handler_is_cancelled_never_released(d, monkeypatch):
    ensure_template()
    app = ready_app(d, monkeypatch)
    # The decision as the previous release recorded it: no notice choice, and a held action nothing ran.
    monkeypatch.setattr(decisions, "_notice_choice", lambda *args: None)
    decision = decide(d, app, "decline")
    assert "decline_notice" not in decision.decision_inputs and decline_actions(app) == []
    old = PendingAction.objects.create(kind="send_decline", subject_type="application", subject_id=app.public_ref,
                                       input_ref=str(decision.public_id), idempotency_key=f"send_decline:{app.public_ref}",
                                       status="held")
    MIGRATION.cancel_held(django_apps, None)
    old.refresh_from_db()
    assert (old.status, old.last_error) == ("cancelled", "held_before_the_decline_handler") and old.completed_at
    # Released by hand anyway: the handler refuses it, because the decision made no choice about the notice.
    PendingAction.objects.filter(pk=old.pk).update(status="queued", due_at=Now(), completed_at=None)
    run_worker()
    old.refresh_from_db()
    assert (old.status, old.last_error) == ("cancelled", "decided_before_the_decline_notice") and notices_of(app) == []


def test_oc4_11_a_member_recorded_on_file_after_the_decline_is_never_sent_a_notice(d, monkeypatch):
    app, _ = declined(d, monkeypatch)
    on_file(app.email_key, "--nda", LABEL_A)
    run_worker()
    [action] = decline_actions(app)
    assert (action.status, action.last_error) == ("cancelled", "member_on_file") and notices_of(app) == []
    assert StaffItem.objects.filter(application=app, reason_code="decline_notice_member_on_file", status="open").count() == 1
    assert not StaffItem.objects.filter(application=app, reason_code="decline_notice_refused").exists()


def test_oc4_11_a_member_recorded_on_file_after_the_freeze_is_skipped_by_the_sender(d, monkeypatch):
    app, _ = declined(d, monkeypatch)
    before = len(d.server.messages)
    assert run_decline_only()  # frozen and queued, not yet sent
    [message] = notices_of(app)
    [send] = sends_of(message)
    assert send.status == "queued"
    on_file(app.email_key, "--nda", LABEL_A)
    run_worker()
    send.refresh_from_db()
    assert (send.status, send.last_error) == ("cancelled", "member_on_file") and len(d.server.messages) == before


def test_oc4_11_a_restore_a_sent_copy_and_a_resolved_unknown_send_item_never_send_a_second_notice(d, monkeypatch):
    from config import post_restore
    from correspondence.staff_items import open_item

    app, _ = declined(d, monkeypatch)
    before = len(d.server.messages)
    # The backup holds the queued `send_decline`; after T it froze and sent the notice, which the restore lost.
    [action] = decline_actions(app)
    assert action.status == "queued" and notices_of(app) == []
    assert "send_decline" in post_restore.outward_kinds()
    report = {}
    post_restore.uncertain_outward(report, post_restore.EffectOpener(None))
    action.refresh_from_db()
    assert (action.status, action.last_error) == ("uncertain", "restore_outward_uncertain")
    assert StaffItem.objects.filter(reason_code=post_restore.ITEM_OUTWARD, pending_action_id=action.pk,
                                    status="open").count() == 1
    # The Sent read finds the copy that left after T; staff resolve that item.
    item = open_item("restore_effect_unknown_send", "sent:synthetic-decline", application=app)
    StaffItem.objects.filter(pk=item.pk).update(status="resolved")
    run_worker()
    action.refresh_from_db()
    assert action.status == "uncertain"  # never re-queued by itself: the remedy is a staff decision
    assert notices_of(app) == [] and len(d.server.messages) == before


def test_oc4_11_a_notice_copy_under_review_after_a_restore_defers_the_freeze(d, monkeypatch):
    from correspondence.staff_items import open_item

    app, _ = declined(d, monkeypatch)
    item = open_item("restore_effect_unknown_send", "sent:synthetic", application=app)
    run_worker()
    [action] = decline_actions(app)
    assert (action.status, action.last_error) == ("queued", "sent_after_backup_pending_review") and notices_of(app) == []
    StaffItem.objects.filter(pk=item.pk).update(status="resolved")
    due_now(app)
    run_worker()
    assert len(notices_of(app)) == 1


def test_oc4_11_the_handler_is_registered_redeliverable_and_automated():
    handler = ledger.handlers()["send_decline"]
    assert isinstance(handler, SendDecline) and handler.redeliverable and handler.automated
