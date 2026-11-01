"""bgl.5 (034 rows 6, 7 and 9; section 1.2 steps 1 and 2): the first generation's `CAT-XXXX-XXXX` reference on every
application, the reference on applicant subjects when a template version asks for it (016 A1 amended for the reference
alone), and the receipt at the first submission, alone or as the verification mail.

Everything synthetic: the seeded placeholder templates (correspondence migration 0026), example.test addresses, and
wording written here. Tests that send commit real data (`privileged_reset`) and run the real worker command.
"""

import re
from importlib import import_module
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from psycopg import errors

from applications import notices, reference
from applications.links import CONFIRM_PATH
from applications.models import Application, ApplicationEvent, SubmissionVersion
from correspondence import outbound, receipt, verification
from correspondence.models import MessageTemplate, MessageTemplateVersion, OutboundMessage
from correspondence.rendering import TemplateRefused, canonical_digest, check_version, version_digest
from tests.test_intake_notice import template_owner
from tests.test_outbound import QUESTION_BODY, QUESTION_SUBJECT, ask, p2, ready  # noqa: F401  (fixtures)
from tests.test_staff import dossier, logged_in, make_user
from tests.test_system_health import health
from tests.test_worker import FORM, VALID, intake, link_in, worker  # noqa: F401  (fixture)
from workflow.models import PendingAction

SEED = import_module("correspondence.migrations.0026_intake_receipt_templates")
BACKFILL = import_module("applications.migrations.0011_application_reference")
VERIFICATION_SEED = import_module("correspondence.migrations.0020_verification_template")
SUFFIX = re.compile(r" \[(CAT-[0-9A-Z]{4}-[0-9A-Z]{4})\]$")


def ensure_receipt_templates():
    if not MessageTemplate.objects.filter(key=SEED.RECEIPT_KEY).exists():
        SEED.create_templates(MessageTemplate, MessageTemplateVersion)


def receipt_mode(settings, mode):
    settings.CATALYST_INTAKE_RECEIPT = mode != "off"
    settings.CATALYST_RECEIPT_IS_VERIFICATION = mode == "verification"


# --- the reference ------------------------------------------------------------------------------------------------

def test_bgl_5_a_generated_reference_has_the_first_generation_format_and_unambiguous_letters():
    seen = {reference.generate() for _ in range(2000)}
    assert len(seen) == 2000  # 40 random bits: no repeat in a sample this small
    for value in seen:
        assert reference.GENERATED.fullmatch(value) and len(value) == 13 and re.fullmatch(reference.STORED_PATTERN, value)
        assert not set(value[4:]) & set("ILOU")
    assert set("".join(v[4:8] + v[9:] for v in seen)) == set(reference.ALPHABET)  # every letter is drawn


def test_bgl_5_every_application_gets_its_own_reference_at_the_first_submission_and_keeps_it(privileged_reset):
    first = intake()
    other = intake(email="grace@example.test", name="Grace Example")
    assert reference.GENERATED.fullmatch(first.reference) and reference.GENERATED.fullmatch(other.reference)
    assert first.reference != other.reference
    intake(reason="A synthetic second version of the same request.")  # a repeat from the same address
    first.refresh_from_db()
    assert Application.objects.filter(email_key="ada@example.test").count() == 1
    assert Application.objects.get(pk=first.pk).reference == first.reference and first.versions.count() == 2


@pytest.mark.django_db
def test_bgl_5_the_database_holds_the_reference_unique_and_well_formed_and_an_import_keeps_its_own():
    kept = Application.objects.create(email="old@example.test", email_key="old@example.test", display_name="Synthetic",
                                      reference="CAT-AB12-CD34")  # what an importer passes for an existing case
    assert Application.objects.get(pk=kept.pk).reference == "CAT-AB12-CD34"
    with pytest.raises(IntegrityError), transaction.atomic():
        Application.objects.create(email="dup@example.test", email_key="dup@example.test", display_name="Synthetic",
                                   reference="CAT-AB12-CD34")
    for bad in ("CAT-ab12-cd34", "CAT-AB12CD34", "XYZ-AB12-CD34", "CAT-AB1-CD345"):
        with pytest.raises(IntegrityError), transaction.atomic():
            Application.objects.create(email="bad@example.test", email_key="bad@example.test", display_name="Synthetic",
                                       reference=bad)


def test_bgl_5_a_row_inserted_outside_the_orm_gets_a_reference_and_the_application_cannot_change_one(privileged_reset):
    app = privileged_reset.connect("app", autocommit=True)
    # An older application image omits the column. It must still insert successfully after migration.
    made = app.execute("INSERT INTO applications_application (public_ref, email, email_key, display_name, stage,"
                         " next_version_number) VALUES (gen_random_uuid(), 'raw@example.test', 'raw@example.test',"
                         " 'Synthetic', 'submitted', 1) RETURNING reference").fetchone()[0]
    assert reference.GENERATED.fullmatch(made)
    with pytest.raises(errors.InsufficientPrivilege):
        app.execute("UPDATE applications_application SET reference = 'CAT-0000-0000' WHERE reference = %s", [made])
    with pytest.raises(errors.InsufficientPrivilege):  # trigger execution does not grant direct function access
        app.execute("SELECT public.catalyst_application_reference()")


def test_bgl_5_the_backfill_gives_each_existing_application_a_distinct_reference_and_keeps_any_already_set():
    rows = {1: None, 2: "CAT-AAAA-AAAA", 3: None, 4: None}
    imported = SimpleNamespace(objects=SimpleNamespace(values_list=lambda *_: [(3, "CAT-OLD1-ABCD")]))

    class Query:
        def __init__(self, keep):
            self.keep = keep

        def exclude(self, reference):
            return Query(lambda pk: rows[pk] is not None)

        def filter(self, reference=None, pk=None):
            return Query(lambda p: p == pk) if pk is not None else Query(lambda p: rows[p] is None)

        def order_by(self, *_):
            return self

        def values_list(self, field, flat):
            return [pk if field == "pk" else rows[pk] for pk in sorted(rows) if self.keep(pk)]

        def update(self, reference):
            for pk in [p for p in rows if self.keep(p)]:
                rows[pk] = reference

    apps = SimpleNamespace(get_model=lambda app, _: imported if app == "firstgen" else SimpleNamespace(objects=Query(lambda pk: True)))
    BACKFILL.backfill(apps, None)
    assert rows[2] == "CAT-AAAA-AAAA" and len(set(rows.values())) == 4
    assert rows[3] == "CAT-OLD1-ABCD"
    assert all(re.fullmatch(reference.STORED_PATTERN, value) for value in rows.values())


def test_bgl_5_the_reference_is_never_an_authenticator(privileged_reset):
    app = intake()
    # Quoting the reference where the signed link belongs confirms nothing.
    for path in (f"{CONFIRM_PATH}{app.reference}/", f"{CONFIRM_PATH}{app.public_ref}:{app.reference}/"):
        assert Client().get(path).status_code == 404
        assert Client().post(path, {"version": "1"}).status_code == 404
    app.refresh_from_db()
    assert app.contact_verified_at is None
    # No applicant-facing code looks anything up by it (the staff admin's search is staff-only).
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for module in ("applications/views.py", "applications/confirmation.py", "applications/links.py", "applications/urls.py",
                   "provisioning/views.py", "correspondence/inbound.py", "correspondence/processing.py",
                   "correspondence/association.py"):
        source = (root / module).read_text()
        assert not re.search(r"reference(__\w+)?\s*=", source.replace("subject_reference", "")), module


def test_bgl_5_the_staff_dossier_shows_the_reference(privileged_reset):
    app = intake()
    page = dossier(logged_in(make_user(privileged_reset, "reference-reader")), app)
    assert app.reference in page
    received = Client().get(reverse("applications:request_access_received"))
    assert app.reference not in received.content.decode()  # the applicant's page carries no reference (TEST-S1-01)


# --- the subject rule ---------------------------------------------------------------------------------------------

def test_bgl_5_the_version_digest_covers_the_subject_reference_flag_and_subjects_stay_static():
    subject, body = "Synthetic subject", "Synthetic body.\n"
    assert version_digest(subject, body) == canonical_digest(subject, body)  # every existing version keeps its digest
    assert version_digest(subject, body, subject_reference=True) != version_digest(subject, body)
    assert version_digest(subject, body, subject_reference=True) == canonical_digest(subject + " [$reference]", body)
    template = SimpleNamespace(secret_bearing=False)
    version = SimpleNamespace(subject=subject, body_text=body, variables=[], secret_bearing=False, template=template,
                              subject_reference=True, content_sha256=canonical_digest(subject, body))
    with pytest.raises(TemplateRefused, match="^content_digest_mismatch$"):  # flipping the flag breaks the digest
        check_version(version)
    version.content_sha256 = version_digest(subject, body, subject_reference=True)
    check_version(version)
    version.subject = "Hello $reference"
    with pytest.raises(TemplateRefused, match="^placeholder_in_subject$"):  # no variable in a subject (016 A1)
        check_version(version)


def test_bgl_5_the_sender_appends_the_reference_only_when_the_version_asks():
    plain = notices.Wording("k", 1, "0" * 64, "Synthetic subject", "body", approved=True)
    asking = notices.Wording("k", 1, "0" * 64, "Synthetic subject", "body", approved=True, subject_reference=True)
    assert plain.subject_for("CAT-AB12-CD34") == "Synthetic subject"
    assert asking.subject_for("CAT-AB12-CD34") == "Synthetic subject [CAT-AB12-CD34]"
    with pytest.raises(ValueError):
        asking.subject_for("")


def test_bgl_5_an_approved_versions_reference_flag_is_final_for_every_role(privileged_reset):
    ensure_receipt_templates()
    seeded = MessageTemplateVersion.objects.get(template__key=SEED.RECEIPT_KEY, version=1)
    outbound.approve_template_version(seeded.pk, template_owner(privileged_reset, "flag-owner"))
    owner = privileged_reset.connect("owner", autocommit=True)
    with pytest.raises(errors.InsufficientPrivilege):
        owner.execute("UPDATE correspondence_messagetemplateversion SET subject_reference = false WHERE id = %s", [seeded.pk])
    app = privileged_reset.connect("app", autocommit=True)
    with pytest.raises(errors.InsufficientPrivilege):  # no column grant either
        app.execute("UPDATE correspondence_messagetemplateversion SET subject_reference = false WHERE id = %s", [seeded.pk])


def test_bgl_5_the_verification_mail_carries_the_reference_when_its_version_asks(worker, privileged_reset):
    seeded = VERIFICATION_SEED
    if not MessageTemplate.objects.filter(key=seeded.KEY).exists():
        seeded.create_template(MessageTemplate, MessageTemplateVersion)
    app = intake()
    worker()
    assert mail.outbox[0].subject == seeded.SUBJECT  # the seeded version does not ask
    template = MessageTemplate.objects.get(key=seeded.KEY)
    asking = MessageTemplateVersion.objects.create(
        template=template, version=2, subject=seeded.SUBJECT, body_text=seeded.BODY, variables=["link"], secret_bearing=True,
        subject_reference=True, content_sha256=version_digest(seeded.SUBJECT, seeded.BODY, subject_reference=True))
    outbound.approve_template_version(asking.pk, template_owner(privileged_reset, "subject-owner"))
    other = intake(email="grace@example.test", name="Grace Example")
    worker()
    sent = mail.outbox[-1]
    assert sent.to == ["grace@example.test"] and sent.subject == f"{seeded.SUBJECT} [{other.reference}]"
    assert other.reference != app.reference


def test_bgl_5_a_frozen_message_carries_the_reference_when_its_version_asks(ready):
    env = ready
    _, plain = ask(env)
    assert plain.frozen_subject == QUESTION_SUBJECT  # the version does not ask
    asking = MessageTemplateVersion.objects.create(
        template=MessageTemplate.objects.get(key="question_request"), version=2, subject=QUESTION_SUBJECT,
        body_text=QUESTION_BODY, variables=["display_name", "question_text"], subject_reference=True,
        content_sha256=version_digest(QUESTION_SUBJECT, QUESTION_BODY, subject_reference=True))
    outbound.approve_template_version(asking.pk, env.owner)
    _, message = ask(env, "Which synthetic tool did you build?")
    assert message.frozen_subject == f"{QUESTION_SUBJECT} [{env.app.reference}]"
    assert message.content_sha256 == canonical_digest(message.frozen_subject, message.frozen_body)  # the subject as sent


# --- the receipt --------------------------------------------------------------------------------------------------

def test_bgl_5_with_the_receipt_off_intake_is_unchanged(worker, settings):
    receipt_mode(settings, "off")
    intake()
    worker()
    assert not PendingAction.objects.filter(kind="send_receipt").exists()
    [message] = mail.outbox
    assert message.subject == VERIFICATION_SEED.SUBJECT


def test_bgl_5_the_separate_receipt_goes_first_once_and_never_again_for_a_repeat(worker, settings):
    receipt_mode(settings, "separate")
    ensure_receipt_templates()
    app = intake()
    [action] = PendingAction.objects.filter(kind="send_receipt")
    assert action.idempotency_key == f"send_receipt:{app.public_ref}" and action.input_ref == str(app.versions.get().public_id)
    assert action.pk < PendingAction.objects.get(kind="send_verification").pk  # queued first, claimed first
    worker()
    first, verification_mail = mail.outbox
    assert first.to == ["ada@example.test"] and first.subject == f"{SEED.SUBJECT} [{app.reference}]"
    assert first.body.startswith(notices.DRAFT_MARKER) and f"Reference: {app.reference}" in first.body
    assert "Hello Ada," in first.body and CONFIRM_PATH not in first.body  # no link in the separate receipt
    assert verification_mail.subject == VERIFICATION_SEED.SUBJECT and CONFIRM_PATH in verification_mail.body
    row = OutboundMessage.objects.get(template_key=SEED.RECEIPT_KEY)
    assert (row.status, row.recipient, row.template_version) == (
        "accepted", "ada@example.test", f"1:{SEED.digest(SEED.SUBJECT, SEED.BODY)[:24]}")
    sent = app.events.get(kind="receipt_sent")
    assert sent.data == {"attempt": 1, "template_version": 1, "template_sha256": SEED.digest(SEED.SUBJECT, SEED.BODY),
                         "draft": True}
    # A repeat from the same address: a new version, no second receipt (and the live link is reused: no mail at all).
    intake(reason="A synthetic second version of the same request.")
    worker()
    assert len(mail.outbox) == 2 and PendingAction.objects.filter(kind="send_receipt").count() == 1
    assert app.versions.count() == 2


def test_bgl_5_the_receipt_is_the_verification_mail_when_so_configured(worker, settings):
    receipt_mode(settings, "verification")
    ensure_receipt_templates()
    app = intake()
    assert not PendingAction.objects.filter(kind="send_receipt").exists()
    worker()
    [message] = mail.outbox
    assert message.subject == f"{SEED.SUBJECT} [{app.reference}]"
    assert f"Reference: {app.reference}" in message.body and "Hello Ada," in message.body
    link, _ = link_in(message.body)
    row = OutboundMessage.objects.get()
    assert (row.template_key, row.template_version) == (
        SEED.CONFIRM_KEY, f"1:{SEED.digest(SEED.SUBJECT, SEED.CONFIRM_BODY)[:24]}")
    assert app.events.get(kind="verification_sent").data["template_key"] == SEED.CONFIRM_KEY
    # The link in the receipt confirms the address like any verification link.
    path = link.removeprefix("http://catalyst.example.test")
    version = re.search(r'name="version" value="([^"]+)"', Client().get(path).content.decode()).group(1)
    assert Client().post(path, {"version": version}).status_code == 200
    app.refresh_from_db()
    assert app.contact_verified_at is not None
    intake(reason="A synthetic repeat after confirming.")  # no second receipt after verification either
    worker()
    assert len(mail.outbox) == 1


def test_bgl_5_the_receipt_values_follow_the_first_generation():
    assert receipt.greeting("Ada Example") == "Hello Ada"
    assert receipt.greeting("Zoë-Anne O’Neil") == "Hello Zoë-Anne"
    for unplain in ("", "   ", "ada@example.test", "<b>Ada</b>", "1234", "x" * 41, "[erased]"):
        assert receipt.greeting(unplain) == "Hello", unplain
    app = SimpleNamespace(display_name="Ada Example", reference="CAT-AB12-CD34")
    from datetime import UTC, datetime

    version = SimpleNamespace(submitted_fields={"name": "Ada Example", "interest_track": "cert_only"},
                              received_at=datetime(2026, 10, 31, 12, tzinfo=UTC))
    assert receipt.values(app, version) == {"greeting": "Hello Ada", "reference": "CAT-AB12-CD34",
                                            "submitted_on": "31 October 2026", "interest": "Certification support only"}
    version.submitted_fields = {"name": "Ada Example"}  # a form without the field
    assert receipt.values(app, version)["interest"] == ""
    assert set(receipt.values(app, version)) == set(notices.RECEIPT_VARIABLES) == set(SEED.VARIABLES)


def test_bgl_5_a_live_environment_withholds_intake_until_the_receipt_wording_is_approved_and_real(
        privileged_reset, settings):
    ensure_receipt_templates()
    receipt_mode(settings, "separate")
    assert not notices.receipt_withheld()  # a draft environment sends the marked draft
    settings.CATALYST_ENV = "production"
    assert notices.receipt_withheld()
    assert "receipt_template_unapproved" in health()[1]["intake"]["anomalies"]
    seeded = MessageTemplateVersion.objects.get(template__key=SEED.RECEIPT_KEY, version=1)
    real_body = "$greeting,\n\nWe have your request $reference of $submitted_on ($interest).\n"
    real = MessageTemplateVersion.objects.create(
        template=seeded.template, version=2, subject="Synthetic real receipt", body_text=real_body, variables=SEED.VARIABLES,
        subject_reference=True, content_sha256=version_digest("Synthetic real receipt", real_body, subject_reference=True), synthetic=False)
    outbound.approve_template_version(real.pk, template_owner(privileged_reset, "receipt-owner"))
    assert not notices.receipt_withheld()
    receipt_mode(settings, "verification")  # the verification mail is now the receipt with the link: its template decides
    assert notices.verification_template() == notices.RECEIPT_CONFIRM and notices.verification_withheld()
    receipt_mode(settings, "off")
    assert not notices.receipt_withheld()


def test_bgl_5_a_closed_or_paused_application_gets_no_receipt(worker, settings):
    receipt_mode(settings, "separate")
    ensure_receipt_templates()
    app = intake()
    Application.objects.filter(pk=app.pk).update(stage="withdrawn")
    worker()
    action = PendingAction.objects.get(kind="send_receipt")
    assert (action.status, action.last_error) == ("cancelled", "application closed")
    assert not any(m.subject.startswith(SEED.SUBJECT) for m in mail.outbox)
    assert ApplicationEvent.objects.filter(application=app, kind="receipt_send_skipped").exists()
    assert SubmissionVersion.objects.filter(application=app).count() == 1


def test_bgl_5_the_receipt_handler_is_registered_redeliverable_and_reviewed_after_a_restore():
    from config import post_restore
    from workflow import effects, ledger

    handler = ledger.handlers()["send_receipt"]
    assert isinstance(handler, receipt.SendReceipt) and handler.redeliverable and handler.automated
    assert "send_receipt" in post_restore.outward_kinds()
    assert "correspondence.receipt:SendReceipt.run" in effects.REGISTRY
    assert verification.mail_for  # the verification mail chooses its template by the receipt mode


def test_bgl_5_the_request_page_answers_the_same_with_the_receipt_on(privileged_reset, settings):
    receipt_mode(settings, "separate")
    ensure_receipt_templates()
    response = Client().post(FORM, urlencode(VALID), content_type="application/x-www-form-urlencoded")
    assert response.status_code == 302
