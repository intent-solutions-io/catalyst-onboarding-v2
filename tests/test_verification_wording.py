"""9kg.80: the verification mail and the request form's own copy reach a real person only as owner-approved wording.

The verification mail is the `verification_invitation` template (correspondence migration 0020), seeded as a marked,
synthetic draft with the link as its only variable. A local or synthetic environment sends the draft with its marker;
a live environment sends nothing until a real version is approved: the action goes back to the queue under a reason
code, intake is withheld and health reports `verification_template_unapproved`. The outbound row records the version
and a digest prefix, the `verification_sent` event the full digest. The form's fixed sentences show only outside a
live environment.
"""

import logging
from importlib import import_module

import pytest
from django.core import mail
from django.db.models.functions import Now
from django.test import Client

from applications import notices, views
from applications.models import ApplicationEvent
from correspondence import outbound, verification
from correspondence.models import MessageTemplate, MessageTemplateVersion, OutboundMessage
from correspondence.rendering import canonical_digest
from tests.test_intake_notice import template_owner
from tests.test_system_health import health
from tests.test_worker import FORM, handler, intake, link_in, worker  # noqa: F401  (fixture)
from workflow import ledger
from workflow.models import PendingAction

SEED = import_module("correspondence.migrations.0020_verification_template")
REAL_BODY = "Hello,\n\nPlease confirm this address for the onboarding trial:\n\n$link\n\nThe owner\n"


def ensure_template():
    if not MessageTemplate.objects.filter(key=SEED.KEY).exists():
        SEED.create_template(MessageTemplate, MessageTemplateVersion)
    return MessageTemplateVersion.objects.get(template__key=SEED.KEY, version=1)


def approve_real(privileged_reset):
    seeded = ensure_template()
    real = MessageTemplateVersion.objects.create(
        template=seeded.template, version=2, subject=seeded.subject, body_text=REAL_BODY, variables=["link"],
        secret_bearing=True, content_sha256=canonical_digest(seeded.subject, REAL_BODY), synthetic=False)
    return outbound.approve_template_version(real.pk, template_owner(privileged_reset, "verification-owner"))


def send_once():
    claim = ledger.claim_next({"send_verification": handler()})
    assert claim is not None
    handler().run(claim)


def test_9kg_80_the_seed_is_the_code_s_draft_and_a_draft_environment_sends_it_marked(worker):
    seeded = ensure_template()
    assert (seeded.status, seeded.synthetic, seeded.secret_bearing, seeded.variables) == ("draft", True, True, ["link"])
    assert seeded.content_sha256 == canonical_digest(SEED.SUBJECT, SEED.BODY)
    intake()
    worker()
    [message] = mail.outbox
    assert message.subject == SEED.SUBJECT and message.body.startswith(notices.DRAFT_MARKER)
    link_in(message.body)
    row = OutboundMessage.objects.get()
    assert row.template_version == f"1:{seeded.content_sha256[:24]}"
    sent = ApplicationEvent.objects.get(kind="verification_sent")
    assert sent.data == {"attempt": 1, "template_version": 1, "template_sha256": seeded.content_sha256, "draft": True}


def test_9kg_80_without_the_row_a_draft_environment_uses_the_seed_and_a_live_one_refuses(monkeypatch, settings):
    def missing(key, values=None):  # what the source reports after the test reset truncated the templates
        raise notices.Unavailable(f"{key}_missing")

    monkeypatch.setattr(notices, "wording", missing)
    rendered = verification.wording("http://catalyst.example.test/confirm/x/")
    assert (rendered.version, rendered.sha256, rendered.approved) == (1, canonical_digest(SEED.SUBJECT, SEED.BODY), False)
    assert "http://catalyst.example.test/confirm/x/" in rendered.display and rendered.display.startswith(notices.DRAFT_MARKER)
    monkeypatch.setattr(notices, "wording", lambda key, values=None: (_ for _ in ()).throw(
        notices.Unavailable(f"{key}_not_approved")))  # a live environment never reaches the seed
    settings.CATALYST_ENV = "production"
    with pytest.raises(notices.Unavailable, match="^verification_invitation_not_approved$"):
        verification.wording("http://catalyst.example.test/confirm/x/")


def test_9kg_80_a_live_environment_sends_nothing_unapproved_withholds_intake_and_sends_the_approved_version(
        worker, privileged_reset, settings, monkeypatch, caplog):
    ensure_template()
    app = intake()
    settings.CATALYST_ENV = "production"
    send_once()
    action = PendingAction.objects.get(kind="send_verification")
    assert (action.status, action.attempts, action.last_error) == ("queued", 0, "verification_invitation_not_approved")
    assert mail.outbox == [] and OutboundMessage.objects.count() == 0
    # Intake is withheld: no applicant is accepted who could not be sent the mail.
    monkeypatch.setattr(views, "_withheld_logged", {})
    caplog.set_level(logging.WARNING, logger="applications.views")
    assert Client().get(FORM).status_code == 503
    assert "intake page withheld: verification_template_unapproved" in caplog.text
    code, report = health()
    assert code == 1 and "verification_template_unapproved" in report["intake"]["anomalies"]
    assert report["intake"]["verification"]["status"] == "draft"
    # The owner approves real wording: the queued action sends it, recorded by version and digest.
    real = approve_real(privileged_reset)
    PendingAction.objects.filter(pk=action.pk).update(due_at=Now())
    send_once()
    [message] = mail.outbox
    link, _ = link_in(message.body)
    assert message.body == REAL_BODY.replace("$link", link) and notices.DRAFT_MARKER not in message.body
    assert OutboundMessage.objects.get().template_version == f"2:{real.content_sha256[:24]}"
    sent = app.events.get(kind="verification_sent")
    assert sent.data == {"attempt": 1, "template_version": 2, "template_sha256": real.content_sha256, "draft": False}
    # The form is served again, without any of its unapproved fixed sentences.
    page = Client().get(FORM)
    assert page.status_code == 200
    text = page.content.decode()
    assert "Placeholder copy" not in text and "ynthetic" not in text and "A person makes every decision" not in text
    assert "verification_template_unapproved" not in health()[1]["intake"]["anomalies"]


def test_9kg_80_an_approved_synthetic_verification_mail_is_still_refused_in_a_live_environment(
        worker, privileged_reset, settings):
    seeded = ensure_template()
    outbound.approve_template_version(seeded.pk, template_owner(privileged_reset, "drill-owner"))
    intake()
    settings.CATALYST_ENV = "production"
    send_once()
    assert PendingAction.objects.get(kind="send_verification").last_error == "verification_invitation_synthetic"
    assert mail.outbox == [] and notices.verification_withheld()
