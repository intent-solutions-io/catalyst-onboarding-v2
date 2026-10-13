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


def test_p2_42_a_service_refusal_reaches_staff_as_a_code(mailbox):
    question, _ = sent_question(mailbox)
    staff_actions.withdraw_question(question.pk, mailbox.operator, "asked_in_error")
    response = client(mailbox.operator).post(url("withdraw", question.public_id), {"reason": "because"}, follow=True)
    assert "Refused: unknown_withdrawal_reason" in response.content.decode()


# --- review fixes (operator, security and QA reviews of PR #24) --------------------------------------------

def test_p2_42_a_role_reads_only_the_pages_its_work_needs(mailbox):
    from correspondence.roles import TEMPLATE_OWNER

    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message))
    collect()
    received = InboundMessage.objects.get()
    item = StaffItem.objects.get(reason_code="reply_needs_review")
    owner_only = staff(mailbox, "template-owner-2", TEMPLATE_OWNER)
    c = client(owner_only)
    for page in (url("queue"), url("item", item.public_id), url("reply", received.public_id),
                 url("application", mailbox.app.public_ref), url("applications")):
        assert c.get(page).status_code == 403, page  # a template owner never reads applicant mail
    assert c.get(url("templates")).status_code == 200
    assert client(mailbox.operator).get(url("templates")).status_code == 403


def test_p2_42_template_approval_through_the_screen_approves_exactly_what_was_shown(mailbox):
    from correspondence.models import MessageTemplateVersion
    from tests.test_outbound import question_template

    draft = question_template(version=2, body="Hello $display_name,\n\n$question_text\n")
    c = client(mailbox.owner)
    page = c.get(url("template", draft.pk)).content.decode()
    assert "Approve exactly this version" in page and draft.content_sha256 in page
    stale = c.post(url("approve_template", draft.pk), {"digest": "0" * 64}, follow=True)
    assert "Refused: template_changed_since_shown" in stale.content.decode()
    c.post(url("approve_template", draft.pk), {"digest": draft.content_sha256})
    assert MessageTemplateVersion.objects.get(pk=draft.pk).status == "approved"


def test_p2_42_the_item_page_shows_the_evidence_and_offers_only_lawful_decisions(mailbox):
    from correspondence.models import ApprovedMessage

    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, auth="dmarc=fail"))
    collect()
    identity = StaffItem.objects.get(reason_code="reply_auth_failed")
    page = client(mailbox.decider).get(url("item", identity.public_id)).content.decode()
    assert "trust auth_failed" in page and "authentication fail" in page and "Read the message" in page
    sent = ApprovedMessage.objects.get(kind="question")
    rejected = StaffItem.objects.create(reason_code="send_rejected_permanent", dedupe_key=str(sent.send_ref),
                                        application=mailbox.app, approved_message=sent)
    page = client(mailbox.decider).get(url("item", rejected.public_id)).content.decode()
    assert ">abandon<" in page and ">revise<" in page and ">authorize_resend<" not in page
    refused = client(mailbox.decider).post(url("send_decision", rejected.public_id), {"decision": "authorize_resend"},
                                           follow=True)
    assert "Refused: decision_not_offered_for_this_reason" in refused.content.decode()
    assert client(mailbox.operator).post(url("send_decision", rejected.public_id), {"decision": "abandon"}).status_code == 403


def test_p2_42_a_malformed_target_is_refused_not_an_error(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, in_reply_to=False))
    collect()
    item = StaffItem.objects.get(reason_code="unmatched")
    response = client(mailbox.decider).post(url("resolve", item.public_id), {"code": "associate", "target": "not-a-uuid"},
                                            follow=True)
    assert response.status_code == 200 and "Refused: unknown_application" in response.content.decode()


def test_p2_42_applications_can_be_found_without_an_open_item(mailbox):
    Question.objects.create(application=mailbox.app, text="A proposed synthetic question?")
    c = client(mailbox.operator)
    listed = c.get(url("applications") + "?show=proposed").content.decode()
    assert "proposed question" in listed and str(mailbox.app.public_ref) in listed
    found = c.get(url("applications") + f"?ref={mailbox.app.public_ref}").content.decode()
    assert str(mailbox.app.public_ref) in found
    assert c.get(url("applications") + "?ref=junk").status_code == 200


def test_p2_42_a_refused_preview_keeps_the_typed_text_escaped(mailbox):
    response = client(mailbox.operator).post(url("preview_message", mailbox.app.public_ref),
                                             {"subject": "Subject", "body": "<b>keep me</b> password: x"})
    page = response.content.decode()
    assert response.status_code == 200 and "Refused: credential_like_text_refused" in page
    assert "&lt;b&gt;keep me&lt;/b&gt;" in page and "<b>keep me" not in page


@pytest.mark.parametrize("name", ["resume", "pause"])
def test_p2_52_operator_actions_need_the_matching_permission_through_the_screens(mailbox, name):
    owner = mailbox.committed.connect("owner", autocommit=True)
    holder = staff(mailbox, f"only-approve-{name}")
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission"
                  " WHERE codename = 'approve_question'", [holder.pk])
    holder = type(holder).objects.get(pk=holder.pk)
    assert client(holder).post(url(name, mailbox.app.public_ref), {"reason": "a long enough reason"}).status_code == 403


def test_p2_52_restart_needs_the_decision_maker_through_the_screen(mailbox):
    from correspondence.models import MailboxCursor

    MailboxCursor.objects.filter(pk=mailbox.cursor.pk).update(state="blocked", blocked_reason="tls_refused")
    assert client(mailbox.operator).post(url("restart", mailbox.cursor.public_id)).status_code == 403
    client(mailbox.decider).post(url("restart", mailbox.cursor.public_id))
    assert MailboxCursor.objects.get(pk=mailbox.cursor.pk).state != "blocked"



@pytest.mark.parametrize(("permission", "action"), [
    ("pause_automation", "withdraw"), ("pause_automation", "approve"), ("pause_automation", "confirm_message"),
    ("resolve_exception", "confirm_outcome"), ("resolve_exception", "close_reply"),
])
def test_p2_42_52_each_remaining_screen_action_needs_its_own_permission(mailbox, permission, action):
    question, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message))
    collect()
    received = InboundMessage.objects.get()
    draft = staff_actions.preview_staff_message(mailbox.app.pk, mailbox.operator, "Subject", "Body")
    owner = mailbox.committed.connect("owner", autocommit=True)
    holder = staff(mailbox, f"only-{permission}-{action}")
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission"
                  " WHERE codename = %s", [holder.pk, permission])
    target = {"withdraw": (question.public_id,), "approve": (question.public_id,), "confirm_message": (draft.public_id,),
              "confirm_outcome": (received.public_id,), "close_reply": (received.public_id,)}[action]
    data = {"reason": "asked_in_error", "digest": draft.content_sha256, f"q-{question.public_id}": "satisfied"}
    assert client(holder).post(url(action, *target), data).status_code == 403
    question.refresh_from_db()
    received.refresh_from_db()
    assert question.status == "reply_pending" and received.status == "awaiting_processing"


def test_p2_42_template_approval_needs_the_owner_role(mailbox):
    from tests.test_outbound import question_template

    draft = question_template(version=3, body="Hello $display_name,\n\n$question_text\n")
    assert client(mailbox.operator).post(url("approve_template", draft.pk), {"digest": draft.content_sha256}).status_code == 403


# --- GATE-P2 closeout: the operator handoff --------------------------------------------------------------------

def test_the_dossier_links_to_the_correspondence_screen_only_for_a_user_who_could_open_it(mailbox):
    from tests.test_staff import READ_ONLY_STAFF, change_url

    reader = staff(mailbox, "dossier-reader", READ_ONLY_STAFF)
    both = staff(mailbox, "dossier-operator", READ_ONLY_STAFF, "Correspondence operator")
    target = url("application", mailbox.app.public_ref)
    assert target not in client(reader).get(change_url(mailbox.app)).content.decode()
    assert client(reader).get(target).status_code == 403  # the link confers nothing
    page = client(both).get(change_url(mailbox.app)).content.decode()
    assert target in page and "Correspondence screen" in page
    assert client(both).get(target).status_code == 200


def test_operator_journey_through_the_normal_screens(mailbox):
    """One synthetic journey with no SQL and no direct service call for the business actions: the owner approves
    a template, the operator finds the application and approves its question, the applicant replies, the operator
    reads the reply and confirms its outcome, and the remaining work stays visible. Test setup (staff identities,
    the applicant's own S1 flow, a proposed question as P3 or staff authoring would create it) and the worker and
    collector runs are the system, not staff."""
    from correspondence.models import MessageTemplate, MessageTemplateVersion
    from tests.test_reminders import REMINDER_BODY, REMINDER_SUBJECT
    from correspondence.rendering import canonical_digest

    template, _ = MessageTemplate.objects.get_or_create(key="question_reminder", defaults={"purpose": "Remind"})
    draft = MessageTemplateVersion.objects.filter(template=template, version=1).first() or MessageTemplateVersion.objects.create(
        template=template, version=1, subject=REMINDER_SUBJECT, body_text=REMINDER_BODY,
        variables=["display_name", "question_text"], content_sha256=canonical_digest(REMINDER_SUBJECT, REMINDER_BODY))
    question = Question.objects.create(application=mailbox.app, text="Which synthetic project best shows your work?")
    owner, operator = client(mailbox.owner), client(mailbox.operator)
    journey = []

    def step(name, response, expect=200):
        journey.append((name, response.status_code))
        assert response.status_code == expect, (name, response.status_code)
        return response.content.decode() if expect == 200 else ""

    # 1. The owner reads and approves the reminder template, exactly as shown.
    page = step("owner: template list", owner.get(url("templates")))
    assert "question_reminder" in page
    step("owner: template", owner.get(url("template", draft.pk)))
    step("owner: approve template", owner.post(url("approve_template", draft.pk), {"digest": draft.content_sha256}), 302)
    assert MessageTemplateVersion.objects.get(pk=draft.pk).status == "approved"
    # 2. The operator finds the application with a proposed question and approves it.
    page = step("operator: applications with a proposed question", operator.get(url("applications") + "?show=proposed"))
    assert str(mailbox.app.public_ref) in page
    page = step("operator: application", operator.get(url("application", mailbox.app.public_ref)))
    assert "Approve and send" in page
    step("operator: approve question", operator.post(url("approve", question.public_id)), 302)
    run_worker()  # the system sends it
    assert mailbox.server.parsed(-1)["Subject"] == "A question about your application"
    # 3. The applicant replies; the collector and processing run.
    from correspondence.models import ApprovedMessage

    mailbox.imap.deliver(reply(ApprovedMessage.objects.get(kind="question"), body="Project Alpha, partly."))
    collect()
    # 4. The operator sees the work, reads the reply and confirms its outcome.
    page = step("operator: queue", operator.get(url("queue")))
    assert "reply_needs_review" in page
    item = StaffItem.objects.get(reason_code="reply_needs_review")
    page = step("operator: item", operator.get(url("item", item.public_id)))
    received = InboundMessage.objects.get()
    page = step("operator: reply", operator.get(url("reply", received.public_id)))
    assert "Project Alpha, partly." in page
    step("operator: confirm partial", operator.post(url("confirm_outcome", received.public_id), {
        f"q-{question.public_id}": "partial", "digest": received.derived_text_sha256}), 302)
    # 5. The remaining work is visible: the question is partly answered and its reminder is live again.
    page = step("operator: application after", operator.get(url("application", mailbox.app.public_ref)))
    assert "partially_answered" in page
    assert "reply_needs_review" not in step("operator: queue after", operator.get(url("queue")))
    question.refresh_from_db()
    assert question.status == "partially_answered"
    from workflow.models import PendingAction

    assert PendingAction.objects.filter(kind="remind", input_ref__startswith=str(question.public_id),
                                        status="queued").count() == 1  # its reminder is live again
    assert len(journey) == 12 and admin_log_rows(mailbox) == 0
    print("\nOPERATOR JOURNEY: " + "; ".join(f"{n} -> {c}" for n, c in journey))



def test_the_dossier_link_and_the_application_screen_use_the_same_permissions():
    from applications.admin import CORRESPONDENCE_SCREEN_PERMISSIONS
    from correspondence import staff_views

    assert set(CORRESPONDENCE_SCREEN_PERMISSIONS) == set(staff_views.APPLICATION)  # the link never drifts from the gate
