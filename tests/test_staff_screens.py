"""P2 task 2B.4, the permissioned staff screens (016 F; owner decision M9): TEST-P2-42 (each named action needs its
permission, everything else stays read-only, hostile text is escaped) and TEST-P2-52 through the screens.
Synthetic only."""

from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from correspondence import staff_actions
from correspondence.models import InboundMessage, Question, StaffItem
from tests import support
from tests.test_inbound import collect, mailbox, reply, sent_question, tls  # noqa: F401  (fixtures and helpers)
from tests.test_outbound import ask, p2, ready, run_worker, staff  # noqa: F401
from workflow.models import AutomationPause

HOSTILE = "<script>alert(1)</script> \"><img src=x onerror=alert(2)> ‮evil⁦ zero​width ؜ done"


def client(user=None, csrf=False):
    c = Client(enforce_csrf_checks=csrf)
    if user is not None:
        c.force_login(user)
    return c


def url(name, *args):
    return reverse(f"correspondence_staff:{name}", args=args)


def admin_log_rows(env):
    owner = env.committed.connect("owner", autocommit=True)
    return owner.execute("SELECT count(*) FROM django_admin_log").fetchone()[0]


def test_p2_42_pages_need_an_active_staff_account_with_a_correspondence_permission(mailbox):
    nobody = staff(mailbox, "nobody")
    root = staff(mailbox, "root", superuser=True)
    assert client().get(url("queue")).status_code == 302  # to the login page
    assert client(nobody).get(url("queue")).status_code == 403
    assert client(root).get(url("queue")).status_code == 403  # a superuser is refused like everyone else (D-23)
    response = client(mailbox.operator).get(url("queue"))
    assert response.status_code == 200 and "no-store" in response["Cache-Control"]


def test_p2_42_actions_are_post_only_csrf_protected_and_one_object_each(mailbox):
    page = url("pause", mailbox.app.public_ref)
    assert client(mailbox.operator).get(page).status_code == 405
    assert client(mailbox.operator, csrf=True).post(page, {"reason": "a long enough reason"}).status_code == 403
    assert not AutomationPause.objects.exists()
    patterns = [str(p.pattern) for p in __import__("correspondence.staff_urls", fromlist=["x"]).urlpatterns]
    assert all(p.count("<") <= 1 for p in patterns)  # no URL names more than one object; no list parameter


@pytest.mark.parametrize(("name", "data"), [
    ("pause", {"reason": "a long enough reason"}),
    ("preview_message", {"subject": "Subject", "body": "Body"}),
])
def test_p2_42_each_application_action_needs_its_permission(mailbox, name, data):
    no_controls = staff(mailbox, "readonly-ish")
    owner = mailbox.committed.connect("owner", autocommit=True)
    # A user holding only one unrelated correspondence permission sees pages but cannot act.
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission"
                  " WHERE codename = 'approve_template_version'", [no_controls.pk])
    assert client(no_controls).post(url(name, mailbox.app.public_ref), data).status_code == 403
    assert not AutomationPause.objects.exists()


def test_p2_42_pause_resume_withdraw_and_approve_through_the_screens(mailbox):
    c = client(mailbox.operator)
    app = mailbox.app.public_ref
    assert c.post(url("pause", app), {"reason": "short"}).status_code == 302  # refused with a code, not a crash
    assert not AutomationPause.objects.exists()
    c.post(url("pause", app), {"reason": "staff take over for the test"})
    assert AutomationPause.objects.count() == 1
    assert "paused by" in c.get(url("application", app)).content.decode()
    c.post(url("resume", app), {"note": ""})
    assert not AutomationPause.objects.exists()
    question = Question.objects.create(application=mailbox.app, text="A synthetic question?")
    c.post(url("approve", question.public_id))
    question.refresh_from_db()
    assert question.approval_state == "approved"
    c.post(url("withdraw", question.public_id), {"reason": "asked_in_error", "note": "typo"})
    question.refresh_from_db()
    assert question.status == "withdrawn"
    assert admin_log_rows(mailbox) == 0


def test_p2_42_reply_confirmation_shows_the_derivative_escaped_and_checks_its_digest(mailbox):
    question, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body=HOSTILE))
    collect()
    received = InboundMessage.objects.get()
    page = client(mailbox.operator).get(url("reply", received.public_id)).content.decode()
    assert "<script>" not in page and "<img" not in page and "&lt;script&gt;" in page
    for raw, marker in (("‮", "[U+202E]"), ("⁦", "[U+2066]"), ("​", "[U+200B]"), ("؜", "[U+061C]")):
        assert raw not in page and marker in page
    c = client(mailbox.operator)
    stale = c.post(url("confirm_outcome", received.public_id), {f"q-{question.public_id}": "satisfied", "digest": "0" * 64})
    assert stale.status_code == 302
    received.refresh_from_db()
    assert received.status == "awaiting_processing"  # a reply re-derived since it was shown is refused
    c.post(url("confirm_outcome", received.public_id),
           {f"q-{question.public_id}": "satisfied", "digest": received.derived_text_sha256})
    question.refresh_from_db()
    received.refresh_from_db()
    assert question.status == "satisfied" and received.status == "processed"


def test_p2_42_identity_resolution_needs_the_decision_maker_through_the_screen(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, in_reply_to=False))
    collect()
    item = StaffItem.objects.get(reason_code="unmatched")
    page = client(mailbox.operator).get(url("item", item.public_id)).content.decode()
    assert ">dismiss<" in page and ">associate<" not in page  # buttons only for resolutions the viewer holds
    data = {"code": "associate", "target": str(mailbox.app.public_ref)}
    assert client(mailbox.operator).post(url("resolve", item.public_id), data).status_code == 403
    client(mailbox.decider).post(url("resolve", item.public_id), data)
    item.refresh_from_db()
    assert item.status == "resolved"


def test_p2_42_staff_message_preview_and_confirmation_through_the_screens(mailbox):
    c = client(mailbox.operator)
    app = mailbox.app.public_ref
    refused = c.post(url("preview_message", app), {"subject": "About your application", "body": HOSTILE}, follow=True)
    assert "Refused: control_characters_refused" in refused.content.decode()  # bidi controls never enter a message
    preview = c.post(url("preview_message", app), {"subject": "About your application",
                                                    "body": "<script>alert(1)</script> \"><img src=x onerror=alert(2)>"})
    page = preview.content.decode()
    assert preview.status_code == 200 and "<script>" not in page and "<img" not in page and "ada@example.test" in page
    from correspondence.models import StaffMessageDraft

    draft = StaffMessageDraft.objects.get()
    assert c.post(url("confirm_message", draft.public_id), {"digest": "0" * 64}).status_code == 302
    assert not draft.__class__.objects.filter(approved_message__isnull=False).exists()
    c.post(url("confirm_message", draft.public_id), {"digest": draft.content_sha256})
    run_worker()
    assert mailbox.server.parsed(-1)["Subject"] == "About your application"


def test_p2_42_the_queue_and_item_pages_escape_hostile_application_names(mailbox):
    owner = mailbox.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE applications_application SET display_name = %s WHERE id = %s", [HOSTILE, mailbox.app.pk])
    StaffItem.objects.create(reason_code="processing_error", dedupe_key="synthetic:1", application=mailbox.app)
    for page in (client(mailbox.operator).get(url("queue")), client(mailbox.operator).get(url("application", mailbox.app.public_ref))):
        text = page.content.decode()
        assert page.status_code == 200 and "<script>" not in text and "‮" not in text and "[U+202E]" in text


def test_p2_42_the_admin_stays_read_only_and_templates_never_mark_text_safe():
    from config.staff_admin import ReadOnlyAdminMixin

    assert ReadOnlyAdminMixin.actions is None
    for path in Path(support.ROOT, "correspondence", "templates").rglob("*.html"):
        text = path.read_text()
        assert "|safe" not in text and "autoescape off" not in text, path.name
    views = Path(support.ROOT, "correspondence", "staff_views.py").read_text()
    assert "mark_safe" not in views and "format_html" not in views and "log_change" not in views


def test_p2_52_a_service_refusal_reaches_staff_as_a_code(mailbox):
    question, _ = sent_question(mailbox)
    staff_actions.withdraw_question(question.pk, mailbox.operator, "asked_in_error")
    response = client(mailbox.operator).post(url("withdraw", question.public_id), {"reason": "because"}, follow=True)
    assert "Refused: unknown_withdrawal_reason" in response.content.decode()
