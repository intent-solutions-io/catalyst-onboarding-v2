"""Bead catalyst-v2-bgl.7 (parity inventory 034 rows 34 and 21): the signing reminder five business days after an
envelope is issued unsigned, the seam agreements.signing_mail leaves for bead bgl.8, the lapse that follows a reminder
by ten quiet business days, and the signature that reopens a lapsed application.

Against the local fake Documenso (tests/test_agreements.py fixture chain) and the scripted SMTP server of `p2`.
"""

from datetime import timedelta
from importlib import import_module

import pytest

from django.db.models.functions import Now
from django.utils import timezone

from agreements import signing_mail, signing_reminder
from applications.models import Application, ApplicationEvent
from correspondence import outbound, staff_actions
from correspondence.models import ApprovedMessage, MailboxCursor, MessageTemplate, MessageTemplateVersion, StaffItem
from correspondence.roles import OPERATOR, TEMPLATE_OWNER
from tests.test_agreements import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, approve, c, d, ev, g, grant, issued, nda, p2, run_worker, tls,
)
from tests.test_outbound import staff
from workflow import business_days
from workflow.models import PendingAction

LAPSE_MIGRATION = import_module("correspondence.migrations.0021_lapse_note")


@pytest.fixture
def s(g, settings):
    """`g` at the first-generation signing cadence, with an issued, unsigned NDA envelope."""
    settings.CATALYST_SIGNING_REMINDER_MAX = 1
    settings.CATALYST_SIGNING_REMINDER_BUSINESS_DAYS = 5
    settings.CATALYST_LAPSE_AFTER_BUSINESS_DAYS = 10
    settings.CATALYST_REMINDER_QUIET_START_HOUR = settings.CATALYST_REMINDER_QUIET_END_HOUR = 0
    settings.CATALYST_REMINDER_STALE_RETRY_SECONDS = 3600
    return g


def reminders_for(instance):
    return list(PendingAction.objects.filter(kind="remind_signing", input_ref__startswith=str(instance.public_id)).order_by("id"))


def lapses():
    return list(PendingAction.objects.filter(kind="lapse").order_by("id"))


def due_now(kind):
    PendingAction.objects.filter(kind=kind, status="queued").update(due_at=Now())
    run_worker()


def reads_now():
    PendingAction.objects.filter(kind="read_agreement", status="queued").update(due_at=timezone.now())
    run_worker()


def events(app, kind):
    return list(ApplicationEvent.objects.filter(application=app, kind=kind).order_by("id"))


def approve_lapse_wording(env):
    owner = staff(env, "lapse-template-owner", TEMPLATE_OWNER)
    version = MessageTemplateVersion.objects.filter(template__key="lapse_note", version=1).first()
    if version is None:
        LAPSE_MIGRATION.create_template(MessageTemplate, MessageTemplateVersion)
        version = MessageTemplateVersion.objects.get(template__key="lapse_note", version=1)
    outbound.approve_template_version(version.pk, owner)


def collection_complete():
    """A completed-collection watermark ahead of now (016 4.1): the agreements fixtures run no IMAP collector, and a
    lapse never treats an uncollected mailbox as silence."""
    MailboxCursor.objects.update_or_create(mailbox_ref="applicants", folder="INBOX",
                                           defaults={"complete_through_at": timezone.now() + timedelta(hours=1),
                                                     "start_mode": "from_now"})


def test_bgl7_issuing_an_envelope_schedules_one_signing_reminder_five_business_days_on(s, monkeypatch):
    app = issued(s, monkeypatch)
    instance = nda(app)
    assert (instance.issue_status, instance.signing_status, app.stage) == ("issued", "not_started", "agreements")
    [reminder] = reminders_for(instance)
    assert reminder.input_ref == f"{instance.public_id}:1" and reminder.status == "queued"
    assert reminder.due_at == business_days.after(reminder.created_at, 5) and reminder.due_at.hour == 0
    run_worker()  # not due: nothing runs
    assert reminders_for(instance)[0].status == "queued" and lapses() == []
    handler = __import__("workflow.ledger", fromlist=["handlers"]).handlers()["remind_signing"]
    assert type(handler).__name__ == "RemindSigning" and handler.automated and handler.redeliverable


def test_bgl7_without_a_service_signing_mail_the_reminder_records_once_that_the_applicant_was_not_reminded(s, monkeypatch):
    app = issued(s, monkeypatch)
    instance = nda(app)
    assert signing_mail.available() is False
    due_now("remind_signing")
    [reminder] = reminders_for(instance)
    assert reminder.status == "done"
    [withheld] = events(app, "signing_reminder_withheld")
    assert withheld.data == {"instance": str(instance.public_id), "n": 1, "reason": signing_mail.NOT_AVAILABLE}
    assert StaffItem.objects.filter(application=app, reason_code="signing_reminder_unavailable", status="open").count() == 1
    assert lapses() == [] and not events(app, "signing_reminder_queued")  # nothing was sent, so nothing lapses
    assert [m["kind"] for m in s.fake.emails] == ["signing_request"]  # Documenso's own distribution; nothing more
    due_now("remind_signing")
    run_worker()
    assert len(events(app, "signing_reminder_withheld")) == 1 and len(reminders_for(instance)) == 1


def test_bgl7_through_the_seam_the_reminder_goes_once_and_the_lapse_and_the_signature_follow(s, monkeypatch):
    app = issued(s, monkeypatch)
    instance = nda(app)
    sent = []

    def resend_link(instance, *, actor_ref):  # bgl.8's job: database rows only, as the contract says
        sent.append((str(instance.public_id), actor_ref))
        return f"synthetic-send-ref-{len(sent)}"

    monkeypatch.setattr(signing_reminder.signing_mail, "resend_link", resend_link)
    due_now("remind_signing")
    assert sent == [(str(instance.public_id), f"pending_action:{reminders_for(instance)[0].pk}")]
    [queued] = events(app, "signing_reminder_queued")
    assert queued.data == {"instance": str(instance.public_id), "n": 1, "send_ref": "synthetic-send-ref-1"}
    assert len(reminders_for(instance)) == 1  # the maximum is one: no second reminder is scheduled
    [lapse] = lapses()
    assert lapse.input_ref == f"agreement:{instance.public_id}" and lapse.due_at == business_days.after(lapse.created_at, 10)
    due_now("remind_signing")
    run_worker()
    assert len(sent) == 1  # a finished reminder is never run again
    # Ten quiet business days later (made due): the application lapses from `agreements` with one closing note.
    approve_lapse_wording(s)
    collection_complete()
    due_now("lapse")
    assert Application.objects.get(pk=app.pk).stage == "lapsed"
    [moved] = events(app, "application_lapsed")
    assert moved.data == {"from": "agreements", "to": "lapsed", "trigger": f"agreement:{instance.public_id}"}
    [note] = ApprovedMessage.objects.filter(application=app, kind="lapse_note")
    assert note.disposition == "accepted_by_server" and lapses()[0].status == "done"
    assert nda(Application.objects.get(pk=app.pk)).issue_status == "issued"  # nothing is cancelled at the provider
    # The applicant signs after all: the next read reopens the application to `agreements`, then verifies as usual.
    s.fake.sign(instance.envelope_id)
    reads_now()
    app = Application.objects.get(pk=app.pk)
    [reopened] = events(app, "application_reopened")
    assert reopened.data == {"from": "lapsed", "to": "agreements", "trigger": f"signature:{instance.public_id}"}
    assert nda(app).signing_status == "signing_complete_verified"
    assert app.stage in ("agreements", "agreements_complete")  # the D-15 sequence continues from where it lapsed
    assert ApprovedMessage.objects.filter(application=app, kind="lapse_note").count() == 1


def test_bgl7_a_signature_before_the_reminder_cancels_it_and_a_pause_holds_it(s, monkeypatch):
    app = issued(s, monkeypatch)
    instance = nda(app)
    operator = staff(s, "signing-reminder-operator", OPERATOR)
    staff_actions.pause(app.pk, operator, "Checking the applicant's details first")  # the audited staff pause (F)
    due_now("remind_signing")
    assert reminders_for(instance)[0].status == "queued"  # an automated kind is never claimed while paused
    staff_actions.resume(app.pk, operator, "Details checked, carry on")
    s.fake.sign(instance.envelope_id)
    reads_now()
    assert nda(app).signing_status == "signing_complete_verified"
    due_now("remind_signing")
    [reminder] = reminders_for(instance)
    assert (reminder.status, reminder.last_error) == ("cancelled", "agreement_moved")
    assert not events(app, "signing_reminder_withheld") and not events(app, "signing_reminder_queued") and lapses() == []


def test_bgl7_closing_the_application_cancels_its_signing_reminder_and_its_lapse(s, monkeypatch):
    """A closed or withdrawn application is reminded of nothing and never lapses; left queued (under a pause, for good)
    the follow-ups would also keep the person's erasure refused as open work (9kg.87's rule)."""
    from provisioning import closure

    app = issued(s, monkeypatch)
    instance = nda(app)
    signing_reminder.schedule_lapse(instance)  # as after a reminder went out through the seam
    closer = grant(s, staff(s, "signing-closer"), "close_application")
    closure.close_application(app.pk, closer, "closed", "Programme ended for this applicant")
    assert Application.objects.get(pk=app.pk).stage == "closed"
    assert [(x.kind, x.status, x.last_error) for x in reminders_for(instance) + lapses()] == [
        ("remind_signing", "cancelled", "application_closed"), ("lapse", "cancelled", "application_closed")]
