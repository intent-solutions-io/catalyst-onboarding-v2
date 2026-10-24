"""9kg.41 (029 appendix B): the screen and exceptional-state walkthrough, through the real Django views.

Each test drives one or more states of 029 section 5.2 with synthetic data and walks the screen a staff member or
applicant would use: what the page says, the exit it offers, and what a second, accidental submit does. States that
other files already walk through the views are named in 029 appendix B with their tests; this file covers the rest
and the fixes the walkthrough made (labels, form values kept on a refusal, a double submit that acts once). Synthetic
only: the scripted mail servers, the fake Documenso and the fake mail host.

There is no browser in the test tooling, so the phone check is a rendered-HTML check: every page template carries the
viewport declaration, and the public pages carry the phone-width rules (long text wraps, form controls never overflow).
"""

import re
from urllib.parse import urlencode

from django.core import mail
from django.test import Client
from django.urls import reverse

from agreements.models import AgreementInstance
from applications.models import Application, ContactChallenge
from assessments import decisions
from assessments.models import QualificationDecision
from correspondence.models import Question, StaffItem, StaffItemResolution
from provisioning.models import WithdrawalConfirmation
from tests.smtp_server import ScriptedSMTP
from tests.test_agreement_completion import post as webhook, reads_now
from tests.test_clarification import ASK, assessed_with
from tests.test_credentials import invited, post as set_password
from tests.test_decision import rationale, ready_app
from tests.test_evidence import collect as collect_evidence, url
from tests.test_inbound import collect as collect_mail, sent_question
from tests.test_outbound import FORM, VALID, run_worker, staff
from tests.test_processing import bounce, processed
from tests.test_provisioning import complete, release, request_of
from tests.test_reminders import fire
from tests.test_closure import cl  # noqa: F401  (fixture chain)
from tests.test_inbound import mailbox  # noqa: F401
from tests.test_outbound import ready  # noqa: F401
from tests.test_provisioning import a, c, d, ev, g, h, k, p2, pv, tls  # noqa: F401
from tests.test_reminders import remind  # noqa: F401
from workflow.models import AutomationPause, PendingAction

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'


def client_for(user):
    client = Client()
    client.force_login(type(user).objects.get(pk=user.pk))
    return client


def followed(client, path, data=None):
    """POST and follow the redirect: the page the person sees next, with its message."""
    return client.post(path, data or {}, follow=True).content.decode()


# --- correspondence: hard bounce, system pause, uncertain send, escalation ---------------------------------------

def test_walk_a_hard_bounce_and_its_system_pause_through_the_queue_item_and_application_screens(mailbox):
    mailbox.imap.deliver(bounce(sent_question(mailbox)[1]))
    collect_mail()
    processed()
    [item] = StaffItem.objects.filter(reason_code="hard_bounce", status="open")
    operator, decider = client_for(mailbox.operator), client_for(mailbox.decider)
    queue = operator.get(reverse("correspondence_staff:queue")).content.decode()
    assert "hard_bounce" in queue and "1 application(s) paused" in queue
    page = operator.get(reverse("correspondence_staff:item", args=[item.public_id])).content.decode()
    assert "What happened: a message bounced permanently; automation is paused." in page  # plain words (9kg.41)
    assert 'value="address_usable_again"' not in page and "You hold no permission that resolves this item here" in page
    app_page = operator.get(reverse("correspondence_staff:application", args=[mailbox.app.public_ref])).content.decode()
    assert "system safety pause: resuming it needs decision-maker review" in app_page
    resolve = reverse("correspondence_staff:resolve", args=[item.public_id])
    form = {"code": "address_usable_again", "note": "Applicant confirmed the address by phone"}
    assert "Refused: reason_needed" in followed(decider, resolve, {**form, "note": "ok"})
    assert "Resolved." in followed(decider, resolve, form)
    assert "Refused: item_already_resolved" in followed(decider, resolve, form)  # a double submit acts once
    assert StaffItemResolution.objects.filter(item=item).count() == 1
    app_page = decider.get(reverse("correspondence_staff:application", args=[mailbox.app.public_ref])).content.decode()
    assert "Reason (at least 10 characters)" in app_page and "Resume automation" in app_page
    resume = reverse("correspondence_staff:resume", args=[mailbox.app.public_ref])
    assert "Resumed;" in followed(decider, resume, {"note": "The address works again"})
    assert "Refused: not_paused" in followed(decider, resume, {"note": "The address works again"})
    assert not AutomationPause.objects.filter(subject_id=mailbox.app.public_ref).exists()


def test_walk_an_uncertain_send_is_decided_once_on_the_item_page(ready):
    ready.use(ScriptedSMTP({"end": "silent"}))  # the exchange gets no reply: the outcome is unknown
    question = Question.objects.create(application=ready.app, text="Which synthetic project best shows your work?")
    from correspondence import outbound

    message = outbound.approve_question(question.pk, ready.operator)
    run_worker()
    [item] = StaffItem.objects.filter(reason_code="send_outcome_unknown", status="open")
    decider = client_for(ready.decider)
    page = decider.get(reverse("correspondence_staff:item", args=[item.public_id])).content.decode()
    assert "What happened: a send&#x27;s outcome is unknown." in page
    assert 'value="authorize_resend"' in page and "the applicant may receive a duplicate" in page and 'value="abandon"' in page
    decide = reverse("correspondence_staff:send_decision", args=[item.public_id])
    assert "Decision recorded." in followed(decider, decide, {"decision": "abandon", "note": "Sent by hand instead"})
    assert "Refused: nothing_to_decide" in followed(decider, decide, {"decision": "abandon"})  # the second click
    message.refresh_from_db()
    assert message.disposition == "operator_abandoned"
    assert StaffItemResolution.objects.filter(item=item).count() == 1


def test_walk_an_unanswered_question_escalates_to_a_staff_item_with_plain_words(remind):
    question, _ = sent_question(remind)
    fire()
    fire()
    fire()
    [item] = StaffItem.objects.filter(reason_code="escalate_unanswered", question_id=question.pk, status="open")
    operator = client_for(remind.operator)
    assert "escalate_unanswered" in operator.get(reverse("correspondence_staff:queue")).content.decode()
    page = operator.get(reverse("correspondence_staff:item", args=[item.public_id])).content.decode()
    assert "What happened: a question stayed unanswered after the last reminder." in page and 'value="acknowledge"' in page
    resolve = reverse("correspondence_staff:resolve", args=[item.public_id])
    assert "Resolved." in followed(operator, resolve, {"code": "acknowledge", "note": "Called the applicant"})
    assert "Refused: item_already_resolved" in followed(operator, resolve, {"code": "acknowledge"})


# --- verification: the staff resend acts once on a double submit ------------------------------------------------

def test_walk_a_double_submitted_verification_resend_sends_one_message(p2):
    assert Client().post(FORM, urlencode({**VALID, "email": "ada@example.test"}),
                         content_type="application/x-www-form-urlencoded").status_code == 302
    app = Application.objects.get(email_key="ada@example.test")
    operator = client_for(staff(p2, "resender-walk", "Correspondence operator"))
    page = operator.get(reverse("correspondence_staff:application", args=[app.public_ref])).content.decode()
    offered = re.search(r'name="resend_number" value="(\d+)"', page).group(1)
    assert offered == "1"
    url_ = reverse("correspondence_staff:resend_verification", args=[app.public_ref])
    assert "Verification message queued again (resend 1 of 3)." in followed(operator, url_, {"resend_number": offered})
    assert "Refused: resend_already_recorded" in followed(operator, url_, {"resend_number": offered})  # the double click
    assert "Refused: page_out_of_date" in followed(operator, url_, {})  # a form without the number never acts
    assert ContactChallenge.objects.filter(application=app).count() == 2  # the intake one and one resend
    assert app.events.filter(kind="verification_resent").count() == 1
    run_worker()
    assert len(mail.outbox) == 1  # the superseded intake send is cancelled; one message reaches the applicant


# --- the decision and clarification forms keep what was typed ------------------------------------------------

def test_walk_a_refused_decision_keeps_the_typed_reasoning_never_the_outcome_and_a_second_submit_records_nothing(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    decider = client_for(d.decider)
    url_ = reverse("assessments_staff:decide", args=[app.public_ref])
    form = {"digest": decisions.decision_state(app)["digest"], "outcome": "decline", "reason_code": "X",
            "reason_text": "Thin evidence on every criterion."}
    for criterion in rationale():
        form.update({f"cap-{criterion}": "not_shown", f"str-{criterion}": "weak", f"note-{criterion}": f"Typed for {criterion}."})
    refused = decider.post(url_, form)
    page = refused.content.decode()
    assert refused.status_code == 409 and "Refused: reason_code_invalid" in page
    for criterion in rationale():
        assert f'value="Typed for {criterion}."' in page
    assert page.count('<option value="not_shown" selected>') == len(rationale())
    assert 'value="Thin evidence on every criterion."' in page and "choose the outcome again" in page
    assert '<option value="decline" selected>' not in page  # a consequential choice is never carried over
    assert Application.objects.get(pk=app.pk).stage == "awaiting_decision"
    form["reason_code"] = "synthetic_reason"
    assert decider.post(url_, form).status_code == 302
    again = decider.post(url_, form)  # the double click: the state changed, so the digest no longer matches
    assert again.status_code == 409 and "Refused:" in again.content.decode()
    assert QualificationDecision.objects.filter(application=app).count() == 1
    # Declined: the decision screen says nothing more can be recorded, and the dossier shows the queued notice (oc4.11).
    screen = decider.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    assert "not at a stage where a decision can be recorded (declined)" in screen
    reader = staff(d, "dossier-reader-walk", "Read-only staff")
    dossier = client_for(reader).get(reverse("admin:applications_application_change", args=[app.pk])).content.decode()
    assert "send_decline: <strong>queued</strong>" in dossier and "held on policy: no decline notice" not in dossier


def test_walk_a_refused_clarification_keeps_the_typed_question_and_a_double_submit_stores_one(c, monkeypatch):
    from tests.test_assessment import valid

    app, _ = assessed_with(c, monkeypatch, valid())
    author = client_for(c.author)
    url_ = reverse("assessments_staff:author", args=[app.public_ref])
    form = {"text": ASK, "criterion": "no_such_criterion", "gap": "No sample shows the applicant's part.",
            "route": "A short written account.", "requires_evidence": "on"}
    refused = author.post(url_, form)
    page = refused.content.decode()
    assert refused.status_code == 409 and "Refused: unknown_criterion" in page
    assert f'value="{ASK}"' in page and 'value="A short written account."' in page
    assert 'name="requires_evidence" checked' in page
    form["criterion"] = "contribution"
    assert author.post(url_, form).status_code == 302
    again = author.post(url_, form)
    assert again.status_code == 409 and "Refused: duplicate_question" in again.content.decode()
    assert Question.objects.filter(application=app, origin="staff").count() == 1


# --- agreements: the countersignature wait, the age, a refused details draft, a reissue that acts once ----------

def test_walk_the_countersignature_wait_is_named_and_every_agreement_shows_its_age(h, monkeypatch):
    from tests.test_agreements import issued, nda

    app = issued(h, monkeypatch)
    decider = client_for(h.agreement_decider)
    screen = reverse("agreements_staff:agreements", args=[app.public_ref])
    page = decider.get(screen).content.decode()
    assert "Waiting for the applicant to sign, and for custody" in page and "Last status change" in page and " ago)" in page
    instance = nda(app)
    h.fake.sign(instance.envelope_id, complete=False)  # one required signer signed; the countersignature remains
    webhook(h.fake.webhook(instance.envelope_id, "DOCUMENT_SIGNED"))
    reads_now()
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status == "partially_signed"
    page = decider.get(screen).content.decode()
    assert "partly signed" in page and "Waiting for the remaining required signer (the countersignature" in page
    assert "owner: the countersigner, then the system" in page


def test_walk_a_refused_details_draft_keeps_the_typed_values(k, monkeypatch, settings):
    from tests.test_agreements import issued

    settings.CATALYST_AGREEMENT_REQUIRED_DETAILS = {"user_agreement": ["mailing_country", "tax_region"]}  # synthetic
    app = issued(k, monkeypatch)
    decider = client_for(k.agreement_decider)
    act = reverse("agreements_staff:act", args=[app.public_ref])
    refused = decider.post(act, {"action": "record_details", "type": "user_agreement", "field-mailing_country": "Exampleland",
                                 "field-tax_region": "   "})
    page = refused.content.decode()
    assert refused.status_code == 409 and "record_details: refused (field_invalid)" in page
    assert 'name="field-mailing_country" maxlength="200" required autocomplete="off" value="Exampleland"' in page


def test_walk_a_declined_agreement_is_reissued_once_from_the_screen(h, monkeypatch):
    from tests.test_agreements import issued, nda

    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.reject(instance.envelope_id)
    reads_now()
    decider = client_for(h.agreement_decider)
    screen = reverse("agreements_staff:agreements", args=[app.public_ref])
    page = decider.get(screen).content.decode()
    assert "declined" in page and 'value="reissue"' in page and "Automation is paused" in page
    act = reverse("agreements_staff:act", args=[app.public_ref])
    assert decider.post(act, {"action": "reissue", "instance": str(instance.public_id)}).status_code == 302
    again = decider.post(act, {"action": "reissue", "instance": str(instance.public_id)})  # the double click
    assert again.status_code == 409 and "reissue: refused (already_superseded)" in again.content.decode()
    assert AgreementInstance.objects.filter(application=app, agreement_type__key="nda").count() == 2


# --- provisioning: held, provider unavailable at activation, a double-sent withdrawal link -------------------------

def test_walk_held_provisioning_names_the_owner_command(pv, monkeypatch):
    app = complete(pv, monkeypatch)
    page = client_for(pv.approver).get(reverse("provisioning_staff:provisioning", args=[app.public_ref])).content.decode()
    assert "Release provisioning (owner command activate_provisioning)" in page and "(owner: owner)" in page


def test_walk_activation_waiting_on_an_unavailable_provider_is_shown_with_its_reason(pv, monkeypatch, settings):
    app, request, path = invited(pv, monkeypatch)
    settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS = 3600  # the retry is not due within the test
    pv.fake.fault("GET /envelope/", *[("status", 503)] * 6)  # the fresh read before activation cannot reach the provider
    assert set_password(path).status_code == 200
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    [waiting] = PendingAction.objects.filter(kind="provision_activate", status="queued")
    assert waiting.last_error == "provider_unavailable"
    page = client_for(pv.op1).get(reverse("provisioning_staff:provisioning", args=[app.public_ref])).content.decode()
    assert "Password set; activation pending." in page and "Activation waits: provider_unavailable" in page
    assert "It tries again on its own" in page


def test_walk_a_double_requested_withdrawal_link_sends_one_message(cl, monkeypatch):
    app = complete(cl, monkeypatch)
    assert release()["released"] == 1
    closer = client_for(cl.closer)
    act = reverse("provisioning_staff:act", args=[app.public_ref])
    form = {"action": "withdrawal_link", "note": "Applicant asked to withdraw by email"}
    sent = len(mail.outbox)
    assert closer.post(act, form).status_code == 302
    assert closer.post(act, form).status_code == 302  # the double click supersedes the first before it is sent
    run_worker()
    assert len(mail.outbox) == sent + 1
    assert list(WithdrawalConfirmation.objects.filter(application=app).order_by("id").values_list("state", flat=True)) == [
        "superseded", "sent"]
    assert request_of(app).status == "awaiting_approval"  # a link changes nothing until the applicant confirms


# --- the disabled capabilities' refusals, as staff see them ----------------------------------------------------

def test_walk_evidence_fetching_disabled_refuses_every_claim_visibly_and_the_case_moves_on(ev, settings):
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = []  # the launch value: nothing is fetchable (029 section 7)
    app = collect_evidence(ev, work_url_1=url(ev, "/w"), contribution="I wrote the parser.")
    page = client_for(ev.assessor).get(reverse("assessments_staff:evidence", args=[app.public_ref])).content.decode()
    assert "refused (no_approved_source)" in page and "an unavailable or private source never counts against the applicant" in page
    assert ev.site.requests == []  # nothing was fetched
    assert Application.objects.get(pk=app.pk).stage in ("assessing", "awaiting_decision")  # the case moved on


# --- where staff start, and the phone check ---------------------------------------------------------------------

def test_walk_the_admin_index_lists_the_staff_screens_a_role_can_open(mailbox):
    page = client_for(mailbox.operator).get(reverse("admin:index")).content.decode()
    assert "Staff screens (where staff act)" in page and reverse("correspondence_staff:queue") in page
    assert reverse("correspondence_staff:templates") not in page  # the operator holds no template permission
    owner = client_for(mailbox.owner).get(reverse("admin:index")).content.decode()  # the message-template owner
    assert reverse("correspondence_staff:templates") in owner and f'href="{reverse("correspondence_staff:queue")}"' not in owner
    for group, link in (("Agreement template owner", "agreements_staff:templates"),
                        ("Evidence source owner", "assessments_staff:sources")):
        holder = staff(mailbox, f"index-{group.split()[0].lower()}", group)
        assert reverse(link) in client_for(holder).get(reverse("admin:index")).content.decode(), group
    root = staff(mailbox, "root-index", superuser=True)
    assert "Staff screens (where staff act)" not in client_for(root).get(reverse("admin:index")).content.decode()
    reader = staff(mailbox, "index-reader", "Read-only staff")
    assert "Staff screens (where staff act)" not in client_for(reader).get(reverse("admin:index")).content.decode()


def test_walk_every_page_declares_the_phone_viewport_and_the_public_pages_wrap(p2):
    public = Client().get(reverse("applications:request_access")).content.decode()
    assert VIEWPORT in public and "overflow-wrap: anywhere" in public and "max-width: 100%" in public
    assert VIEWPORT in Client().get(reverse("applications:request_access_received")).content.decode()
    invalid = Client().post(reverse("applications:request_access"), {"name": "Ada", "email": "not-an-address",
                                                                     "reason": "A synthetic reason."})
    page = invalid.content.decode()
    assert invalid.status_code == 200 and 'value="Ada"' in page and "A synthetic reason." in page  # kept on an error
    operator = client_for(staff(p2, "viewport-operator", "Correspondence operator"))
    assert VIEWPORT in operator.get(reverse("correspondence_staff:queue")).content.decode()


# --- the operator review of PR #93 ------------------------------------------------------------------------------

def test_walk_a_decision_refused_because_the_case_changed_clears_every_judgment_and_keeps_only_notes(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    decider = client_for(d.decider)
    form = {"digest": "0" * 64, "outcome": "admit", "reason_code": "synthetic_reason", "reason_text": "Typed reason."}
    for criterion in rationale():
        form.update({f"cap-{criterion}": "shown", f"str-{criterion}": "strong", f"note-{criterion}": f"Note for {criterion}."})
    refused = decider.post(reverse("assessments_staff:decide", args=[app.public_ref]), form)
    page = refused.content.decode()
    assert refused.status_code == 409 and "Refused: changed_since_shown" in page
    assert "The case changed since you opened this page; your selections were cleared." in page
    assert " selected>" not in page  # no capability, strength or outcome is carried onto the new state
    assert 'value="synthetic_reason"' not in page and 'value="Typed reason."' not in page
    for criterion in rationale():
        assert f'value="Note for {criterion}."' in page  # only the free-text notes come back
    assert QualificationDecision.objects.filter(application=app).count() == 0


def test_walk_a_suspended_assessment_item_closes_only_through_the_decision_and_links_by_permission(d, settings):
    settings.CATALYST_ASSESSMENT_MODEL = "none"  # the launch: model advice disabled
    app = collect_evidence(d, work_url_1=url(d, "/w"), contribution="I wrote the parser.")
    run_worker()
    [item] = StaffItem.objects.filter(application=app, reason_code="assessment_suspended", status="open")
    page_url = reverse("correspondence_staff:item", args=[item.public_id])
    operator = client_for(staff(d, "item-operator", "Correspondence operator"))
    page = operator.get(page_url).content.decode()
    assert "closes only through the human-only decision recorded there" in page
    assert 'value="acknowledge"' not in page and "You hold no permission that resolves this item here" not in page
    assert reverse("assessments_staff:decision", args=[app.public_ref]) not in page  # the operator cannot open it
    assert "needs a permission you do not hold" in page
    refused = followed(operator, reverse("correspondence_staff:resolve", args=[item.public_id]), {"code": "acknowledge"})
    assert "Refused: resolution_not_allowed_for_this_reason" in refused
    both = client_for(staff(d, "item-both", "Correspondence operator", "Assessment operator"))
    assert reverse("assessments_staff:decision", args=[app.public_ref]) in both.get(page_url).content.decode()
    assert StaffItem.objects.get(pk=item.pk).status == "open"


def test_walk_a_blocked_mail_channel_is_decided_on_the_item_page_and_the_send_goes_once_resent(ready):
    ready.use(ScriptedSMTP({"mail": 550}))  # the mail host refuses the sender: the channel is blocked
    question = Question.objects.create(application=ready.app, text="Which synthetic project best shows your work?")
    from correspondence import outbound

    message = outbound.approve_question(question.pk, ready.operator)
    run_worker()
    [item] = StaffItem.objects.filter(reason_code="smtp_transport_blocked", status="open")
    decider = client_for(ready.decider)
    page = decider.get(reverse("correspondence_staff:item", args=[item.public_id])).content.decode()
    assert "What happened: the mail channel is blocked." in page and 'value="authorize_resend"' in page
    ready.use(ScriptedSMTP())  # the cause is fixed: the mail host accepts again
    decide = reverse("correspondence_staff:send_decision", args=[item.public_id])
    assert "Decision recorded." in followed(decider, decide, {"decision": "authorize_resend", "note": "Relay fixed"})
    assert "Refused: nothing_to_decide" in followed(decider, decide, {"decision": "authorize_resend"})
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "accepted_by_server" and len(ready.server.messages) == 1


def test_walk_a_mailbox_resync_shows_on_the_queue_and_clears_itself(mailbox, settings):
    from tests.test_inbound import reply

    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="one"))
    mailbox.imap.deliver(reply(message, body="two"))
    collect_mail()
    settings.CATALYST_MAIL_BATCH_SIZE = 1
    mailbox.imap.renumber()
    collect_mail()  # a partial resync pass
    operator = client_for(mailbox.operator)
    queue = operator.get(reverse("correspondence_staff:queue")).content.decode()
    assert ": resync;" in queue and "mailbox_uidvalidity_changed" in queue
    collect_mail()
    queue = operator.get(reverse("correspondence_staff:queue")).content.decode()
    assert ": ok;" in queue  # the worker finishes the resync; staff only acknowledge the item


def test_walk_more_double_submits_act_once(mailbox):
    """The staff-message confirm: a second confirmation of the same preview is refused and queues nothing more."""
    from correspondence.models import ApprovedMessage

    operator = client_for(mailbox.operator)
    preview = operator.post(reverse("correspondence_staff:preview_message", args=[mailbox.app.public_ref]),
                            {"subject": "Synthetic subject", "body": "Synthetic body."}).content.decode()
    action = re.search(r'action="(/staff/p2/drafts/[^"]+/confirm/)"', preview).group(1)
    digest = re.search(r'name="digest" value="([0-9a-f]+)"', preview).group(1)
    assert "Staff message confirmed and queued." in followed(operator, action, {"digest": digest})
    assert "Refused: draft_already_confirmed" in followed(operator, action, {"digest": digest})
    assert ApprovedMessage.objects.filter(application=mailbox.app, kind="staff_message").count() == 1


def test_walk_a_double_submitted_rerun_queues_one_run(a, monkeypatch):
    from assessments.models import AssessmentRun
    from tests.test_assessment import assessed, valid

    bad = valid(quote="A quote that appears nowhere in the evidence")
    app, _, _ = assessed(a, monkeypatch, bad, bad)
    runs = AssessmentRun.objects.filter(application=app).count()
    assessor = client_for(a.assessor)
    rerun = reverse("assessments_staff:rerun", args=[app.public_ref])
    assert "A new assessment run was queued." in followed(assessor, rerun, {"note": "Try again."})
    assert "Refused: run_in_flight" in followed(assessor, rerun, {"note": "Try again."})
    assert AssessmentRun.objects.filter(application=app).count() == runs + 1


def test_walk_a_double_submitted_agreement_cancel_cancels_once(k, monkeypatch):
    from tests.test_agreements import issued, nda

    app = issued(k, monkeypatch)
    instance = nda(app)
    decider = client_for(k.agreement_decider)
    act = reverse("agreements_staff:act", args=[app.public_ref])
    assert decider.post(act, {"action": "cancel", "instance": str(instance.public_id)}).status_code == 302
    again = decider.post(act, {"action": "cancel", "instance": str(instance.public_id)})
    assert again.status_code == 409 and "cancel: refused (not_live)" in again.content.decode()
    assert app.events.filter(kind="agreement_cancel_requested").count() == 1


def test_walk_double_submitted_provisioning_approve_and_close_act_once(cl, monkeypatch):
    from provisioning.models import AccessRevocation

    app = complete(cl, monkeypatch)
    assert release()["released"] == 1
    request = request_of(app)
    act = reverse("provisioning_staff:act", args=[app.public_ref])
    approver = client_for(cl.approver)
    form = {"action": "approve", "request": str(request.public_id), "digest": request.approval_digest}
    assert approver.post(act, form).status_code == 302
    again = approver.post(act, form)
    assert again.status_code == 409 and "approve: refused (" in again.content.decode()
    closer = client_for(cl.closer)
    close = {"action": "close", "outcome": "closed", "note": "Synthetic closure for the walkthrough"}
    assert closer.post(act, close).status_code == 302
    revocations = AccessRevocation.objects.filter(request__application=app).count()
    again = closer.post(act, close)
    assert again.status_code == 409 and "close: refused (" in again.content.decode()
    assert Application.objects.get(pk=app.pk).stage == "closed"
    assert AccessRevocation.objects.filter(request__application=app).count() == revocations
