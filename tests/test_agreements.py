"""P4 task 4B.1: agreement records and their database protections, the hardened Documenso client, the activation of
the held NDA, and create and distribute with reconciliation and the P2 send checks (021 sections 2 to 6, 10; D-37,
D-38). TEST-P4-03, 09 to 12, 18, 20, 22, 24 to 26, 28, 30.

Everything runs against the local fake Documenso (`tests/documenso_fake.py`), which is synthetic and returns signing
tokens like the real API does. POL-05 is undecided, so admitted applicants come from the 3B.4 test path, which sets the
authority the code would carry once it is recorded.
"""

import hashlib
import logging
from datetime import timedelta
from io import StringIO

import pytest
from django.core.exceptions import PermissionDenied
from django.core.management import CommandError, call_command
from django.db import connection
from django.utils import timezone
from psycopg import errors

from agreements import handlers, provider, services
from agreements.models import (NOT_LIVE, AgreementInstance, AgreementRecipient, AgreementTemplateVersion, AgreementType,
                               EnvelopeAttempt)
from applications.models import Application
from config import guards
from correspondence.models import StaffItem
from tests.documenso_fake import TOKEN, FakeDocumenso
from tests.test_assessment import a  # noqa: F401  (fixture chain)
from tests.test_clarification import c  # noqa: F401
from tests.test_decision import d, decide, ready_app  # noqa: F401
from tests.test_evidence import ev  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2, run_worker, staff  # noqa: F401
from workflow.models import AutomationPause, PendingAction

PDF = b"%PDF-1.7 synthetic placeholder agreement"
SIGNING_SECRETS = ("secret-signing-token", "/sign/")


def grant(env, user, codename):
    owner = env.committed.connect("owner", autocommit=True)
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission "
                  "WHERE codename = %s", [user.pk, codename])
    return user


def configure(settings, fake, tls):
    settings.CATALYST_AGREEMENT_PROVIDER_URL = f"https://documenso.example.test:{fake.port}/api/v2"
    settings.CATALYST_AGREEMENT_PROVIDER_ADDRESS = "127.0.0.1"
    settings.CATALYST_AGREEMENT_PROVIDER_CA_FILE = tls.ca
    settings.CATALYST_AGREEMENT_PROVIDER_TOKEN = TOKEN


@pytest.fixture
def g(d, tls, settings):
    """`d` (decision authority and a decider) plus the fake Documenso, synthetic timings, an approved NDA template and
    a decision-maker for unknown provider outcomes."""
    fake = FakeDocumenso(tls.documenso).start()
    configure(settings, fake, tls)
    settings.CATALYST_AGREEMENT_DEADLINE_SECONDS = 2
    settings.CATALYST_AGREEMENT_ATTEMPTS = 3
    settings.CATALYST_AGREEMENT_RECONCILE_CHECKS = 2
    settings.CATALYST_AGREEMENT_RECONCILE_GRACE_SECONDS = 0
    settings.CATALYST_AGREEMENT_DISTRIBUTE_SETTLE_SECONDS = 0
    settings.CATALYST_AGREEMENT_ORPHAN_CHECKS = 2
    settings.CATALYST_AGREEMENT_LIST_PAGE_SIZE = 2  # small pages, so the bounded listing pages through
    d.fake = fake
    ref, number, slots = fake.template()
    d.template = AgreementTemplateVersion.objects.create(
        agreement_type=AgreementType.objects.get(key="nda"), version=1, provider_template_ref=ref,
        provider_template_number=number, recipient_slots=slots, pdf_sha256=hashlib.sha256(PDF).hexdigest())
    d.template_owner = grant(d, staff(d, "agreement-owner"), "approve_agreement_template")
    d.agreement_decider = grant(d, staff(d, "agreement-decider"), "decide_uncertain_agreement")
    yield d
    fake.stop()


def approve(env):
    return services.approve_template_version(env.template.pk, env.template_owner, env.template.pdf_sha256)


def admitted(env, monkeypatch):
    app = ready_app(env, monkeypatch)
    decide(env, app, "admit")
    app.refresh_from_db()
    assert app.stage == "admitted"
    return app


def activate(*extra, version="1"):
    out = StringIO()
    call_command("activate_agreements", "--activation-version", version, "--approval-ref", "D-38", *extra, stdout=out)
    return out.getvalue()


def nda(app) -> AgreementInstance:
    return AgreementInstance.objects.exclude(issue_status__in=NOT_LIVE).get(application=app, agreement_type__key="nda")


def items(app, reason):
    return StaffItem.objects.filter(application=app, reason_code=reason, status="open")


def issued(env, monkeypatch):
    app = admitted(env, monkeypatch)
    approve(env)
    activate()
    run_worker()
    return Application.objects.get(pk=app.pk)


# --- TEST-P4-09: activation releases only eligible held issue_nda rows --------------------------------------------

def test_p4_09_activation_releases_only_eligible_held_issue_nda(g, monkeypatch):
    app = admitted(g, monkeypatch)
    action = PendingAction.objects.get(kind="issue_nda")
    assert action.status == "held" and action.input_ref == str(app.qualification_decisions.get().public_id)
    with pytest.raises(CommandError):
        activate(version="2")
    assert '"no_approved_template": 1' in activate()  # nothing released without an approved NDA template
    approve(g)
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    assert '"paused": 1' in activate() and PendingAction.objects.get(pk=action.pk).status == "held"
    AutomationPause.objects.all().delete()
    assert '"released": 1' in activate("--dry-run") and PendingAction.objects.get(pk=action.pk).status == "held"
    assert '"released": 1' in activate()
    assert app.events.filter(kind="agreements_activated", data__approval_ref="D-38").exists()
    assert '"released": 0' in activate()  # a released row is never released twice

    # A changed decision reference at claim time: the handler refuses and returns the action to held (step 1).
    g.committed.connect("owner", autocommit=True).execute(
        "UPDATE workflow_pendingaction SET input_ref = %s WHERE id = %s", ["00000000-0000-0000-0000-000000000000", action.pk])
    run_worker()
    assert PendingAction.objects.get(pk=action.pk).status == "held"
    assert app.events.filter(kind="agreement_issue_refused", data__reason="decision_changed").exists()
    assert Application.objects.get(pk=app.pk).stage == "admitted" and not AgreementInstance.objects.exists()
    assert not g.fake.requests


# --- TEST-P4-10, 03, 24: the happy path, one envelope, no signing secrets ---------------------------------------

def test_p4_10_the_instance_and_its_key_are_committed_before_any_provider_call(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    seen = {}
    real = provider.create_from_template
    probe = g.committed.connect("owner", autocommit=True)  # another session sees only committed rows

    def create(template_ref, external_key, recipients):
        seen["committed"] = probe.execute(
            "SELECT i.issue_status, a.outcome, r.email FROM agreements_agreementinstance i"
            " JOIN agreements_envelopeattempt a ON a.instance_id = i.id JOIN agreements_agreementrecipient r ON r.instance_id = i.id"
            " WHERE i.external_key = %s AND a.external_key = %s", [external_key, external_key]).fetchall()
        return real(template_ref, external_key, recipients)
    monkeypatch.setattr(provider, "create_from_template", create)
    run_worker()
    assert seen["committed"] == [("create_pending", "sending", "ada@example.test")]
    app.refresh_from_db()
    instance = nda(app)
    assert app.stage == "agreements" and instance.issue_status == "issued" and instance.signing_status == "not_started"
    assert instance.custody_status == "not_due"
    assert instance.external_key.startswith("ag_") and "ada" not in instance.external_key  # opaque (021 section 10)
    assert list(instance.recipients.values_list("role", "signing_order", "who", "email")) == [
        ("SIGNER", 1, "applicant", "ada@example.test")]


def test_p4_03_a_duplicate_create_is_never_sent_one_envelope_per_instance(g, monkeypatch):
    app = issued(g, monkeypatch)
    instance = nda(app)
    assert len(g.fake.calls("POST", "/envelope/use")) == 1 and len(g.fake.envelopes) == 1
    env = g.fake.envelopes[instance.envelope_id]
    assert env["externalId"] == instance.external_key and env["status"] == "PENDING"
    sent = g.fake.calls("POST", "/envelope/use")[0]
    assert sent["headers"]["Authorization"] == TOKEN and b'"distributeDocument": false' in sent["body"]
    assert b"subject" not in g.fake.calls("POST", "/envelope/distribute")[0]["body"]  # no custom message (021 section 10)
    # A redelivered create (a second action for the same key) finds the instance no longer pending: nothing is sent.
    PendingAction.objects.create(kind="create_agreement", subject_type="application", subject_id=app.public_ref,
                                 input_ref=str(instance.public_id), idempotency_key=f"create_agreement:{instance.public_id}:again")
    run_worker()
    assert len(g.fake.calls("POST", "/envelope/use")) == 1 and len(g.fake.envelopes) == 1


def test_p4_24_signing_tokens_and_links_are_never_stored_or_logged(g, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    app = issued(g, monkeypatch)
    assert "token" in str(g.fake.envelopes) and "signingUrl" in str(g.fake.envelopes)  # the fake does return them
    owner = g.committed.connect("owner", autocommit=True)
    tables = [r[0] for r in owner.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]  # every table
    for table in tables:
        dump = str(owner.execute(f"SELECT * FROM {table}").fetchall())  # noqa: S608 (fixed table names)
        assert not any(s in dump for s in SIGNING_SECRETS), table
    assert not any(s in caplog.text for s in SIGNING_SECRETS) and TOKEN not in caplog.text
    parsed = provider.read(nda(app).envelope_id)
    assert set(vars(parsed.recipients[0])) == {"email", "role", "signing_order", "signing_status"}


# --- TEST-P4-11, 30: unknown creates ---------------------------------------------------------------------------

def test_p4_11_an_unknown_create_reconciles_on_admissible_evidence(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    # Envelopes from other keys or recipients are never evidence; they also push ours to a later page.
    g.fake.fault("POST /envelope/use", ("drop_after",))  # created at the provider, the answer lost
    real = provider.create_from_template

    def create(template_ref, external_key, recipients):
        try:
            return real(template_ref, external_key, recipients)
        finally:
            for key in ("ag_other1", "ag_other2"):
                g.fake.add_envelope(template_ref=g.template.provider_template_ref, external_id=key,
                                    recipients=[{"id": 7001, "email": "ada@example.test"}])
            g.fake.add_envelope(template_ref=g.template.provider_template_ref, external_id=external_key,
                                recipients=[{"id": 7001, "email": "someone-else@example.test"}])
    monkeypatch.setattr(provider, "create_from_template", create)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert len(g.fake.calls("POST", "/envelope/use")) == 1  # never a blind retry
    assert instance.issue_status == "issued" and instance.envelope_id == "envelope_0001"
    attempt = instance.attempts.get(step="create")
    assert attempt.outcome == "found_by_evidence" and attempt.envelope_id == "envelope_0001"
    assert len(g.fake.calls("GET", "/envelope")) >= 2  # paged through the bounded listing
    assert app.events.filter(kind="agreement_envelope_found").exists() and not items(app, handlers.CREATE_UNKNOWN).exists()


def test_p4_11_with_no_evidence_a_decision_maker_decides_and_p4_30_a_late_orphan_is_cancelled(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/use", ("drop_before",))  # sent, never processed: the outcome is still unknown to us
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    first_key = instance.external_key
    assert instance.issue_status == "create_uncertain" and len(g.fake.calls("POST", "/envelope/use")) == 1
    assert items(app, handlers.CREATE_UNKNOWN).count() == 1 and not g.fake.envelopes
    for user in (g.decider, staff(g, "root-p4", superuser=True)):  # only the named permission decides
        with pytest.raises(PermissionDenied):
            services.decide_uncertain_create(instance.pk, user, "not_sent")
    decided = services.decide_uncertain_create(instance.pk, g.agreement_decider, "not_sent")
    assert decided.external_key != first_key and decided.issue_status == "create_pending"  # a new key (P4-D-19)
    old = EnvelopeAttempt.objects.get(external_key=first_key)
    assert old.outcome == "decided_not_sent"  # never rewritten to a known "not sent"
    assert not items(app, handlers.CREATE_UNKNOWN).exists()
    # The first request turns up late at the provider, already sent to the applicant.
    g.fake.add_envelope(template_ref=g.template.provider_template_ref, external_id=first_key, status="PENDING",
                        recipients=[{"id": 7001, "email": "ada@example.test"}])
    run_worker()
    instance.refresh_from_db()
    orphan_id = EnvelopeAttempt.objects.get(pk=old.pk).envelope_id
    assert instance.issue_status == "issued" and instance.envelope_id and instance.envelope_id != orphan_id
    assert EnvelopeAttempt.objects.get(pk=old.pk).outcome == "orphan_found"
    assert g.fake.envelopes[orphan_id]["status"] == "CANCELLED" and len(g.fake.calls("POST", "/envelope/cancel")) == 1
    assert items(app, handlers.LATE_ORPHAN).count() == 1
    assert instance.signing_status == "not_started"  # an orphan is never linked or verified
    with pytest.raises(services.Refused, match="not_uncertain"):
        services.decide_uncertain_create(instance.pk, g.agreement_decider, "not_sent")


def test_p4_11_abandon_cancels_the_instance_and_keeps_watching_the_key(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    services.decide_uncertain_create(instance.pk, g.agreement_decider, "abandon")
    instance.refresh_from_db()
    assert instance.issue_status == "cancelled" and len(g.fake.calls("POST", "/envelope/use")) == 1
    run_worker()
    assert PendingAction.objects.filter(kind="reconcile_agreement", idempotency_key__contains=":watch:").count() == 2
    assert not AgreementInstance.objects.filter(application=app).exclude(pk=instance.pk).exists()


# --- TEST-P4-12: distribute ------------------------------------------------------------------------------------

def test_p4_12_distribute_rereads_first_and_never_distributes_twice(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()

    def mark_pending(self, claim, result):  # the envelope was already distributed when the step re-reads
        if not isinstance(result, provider.ProviderError):
            g.fake.envelopes[result]["status"] = "PENDING"
    monkeypatch.setattr(handlers.CreateAgreement, "after_call", mark_pending)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "issued" and not g.fake.calls("POST", "/envelope/distribute")
    assert instance.attempts.get(step="distribute").outcome_code == "already_distributed"
    assert len(g.fake.calls("GET", f"/envelope/{instance.envelope_id}")) == 1


def test_p4_12_an_unknown_distribute_reconciles_without_a_second_send(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/distribute", ("drop_after",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "issued" and len(g.fake.calls("POST", "/envelope/distribute")) == 1
    assert instance.attempts.get(step="distribute").outcome == "found_by_evidence"
    assert g.fake.envelopes[instance.envelope_id]["status"] == "PENDING"


def test_p4_12_a_distribute_still_unknown_after_the_settle_window_goes_to_a_decision_maker(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/distribute", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "distribute_uncertain" and len(g.fake.calls("POST", "/envelope/distribute")) == 1
    assert items(app, handlers.DISTRIBUTE_UNKNOWN).count() == 1
    assert g.fake.envelopes[instance.envelope_id]["status"] == "DRAFT"


# --- TEST-P4-18: rate limits and an unavailable provider (create and distribute) --------------------------------

def test_p4_18_a_429_is_honoured_and_a_down_provider_goes_to_staff(g, monkeypatch, settings):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/use", ("status", 429, {"Retry-After": "30"}))
    run_worker()
    action = PendingAction.objects.get(kind="create_agreement")
    assert action.status == "queued" and action.last_error == "rate_limited"
    wait = (action.due_at - timezone.now()).total_seconds()
    assert 20 < wait <= 31  # Retry-After honoured, within the attempt bound
    assert EnvelopeAttempt.objects.get().outcome == "not_sent" and not g.fake.envelopes
    PendingAction.objects.filter(pk=action.pk).update(due_at=timezone.now() - timedelta(seconds=1))
    settings.CATALYST_AGREEMENT_PROVIDER_URL = "https://documenso.example.test:9/api/v2"  # nothing listens
    run_worker()
    action.refresh_from_db()
    instance = nda(Application.objects.get(pk=app.pk))
    assert action.status == "failed" and instance.issue_status == "failed_needs_staff"
    assert items(app, handlers.PROVIDER_UNAVAILABLE).count() == 1 and not g.fake.envelopes
    assert set(instance.attempts.values_list("outcome", flat=True)) == {"not_sent"}


def test_p4_18_a_definite_rejection_goes_to_staff_without_a_retry(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/distribute", ("status", 400))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "failed_needs_staff" and len(g.fake.calls("POST", "/envelope/distribute")) == 1
    assert items(app, handlers.PROVIDER_REJECTED).count() == 1


# --- TEST-P4-22, 25: pause and the P2 send checks ----------------------------------------------------------------

def test_p4_22_a_pause_stops_create_and_distribute(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    pause = AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic",
                                           actor_ref="t")
    run_worker()
    assert not g.fake.requests and PendingAction.objects.get(kind="issue_nda").status == "queued"
    pause.delete()
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "issued" and instance.attempts.filter(step="create").count() == 1


def test_p4_22_a_pause_after_create_holds_the_distribute(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()

    def pause_now(self, claim, result):
        AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    monkeypatch.setattr(handlers.CreateAgreement, "after_call", pause_now)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "distribute_pending" and not g.fake.calls("POST", "/envelope/distribute")
    AutomationPause.objects.all().delete()
    monkeypatch.setattr(handlers.CreateAgreement, "after_call", lambda self, claim, result: None)
    run_worker()
    assert nda(Application.objects.get(pk=app.pk)).issue_status == "issued"


@pytest.mark.parametrize("problem", ["hard_bounce", "recipient_changed"])
def test_p4_25_distribute_refuses_when_a_p2_send_check_fails(g, monkeypatch, problem):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()

    def after_create(self, claim, result):
        if problem == "hard_bounce":
            StaffItem.objects.create(application=Application.objects.get(pk=app.pk), reason_code="hard_bounce",
                                     dedupe_key="inbound:synthetic")
        else:
            monkeypatch.setattr(handlers, "verified_address", lambda application: "changed@example.test")
    monkeypatch.setattr(handlers.CreateAgreement, "after_call", after_create)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "failed_needs_staff" and not g.fake.calls("POST", "/envelope/distribute")
    assert items(app, handlers.DISTRIBUTE_REFUSED).count() == 1
    assert g.fake.envelopes[instance.envelope_id]["status"] == "DRAFT"  # created, never sent to anyone


# --- TEST-P4-26: database protections, bypassing the services -------------------------------------------------

def ua_template(env):
    version = AgreementTemplateVersion.objects.create(
        agreement_type=AgreementType.objects.get(key="user_agreement"), version=1, provider_template_ref="envelope_template_ua",
        provider_template_number=102, recipient_slots={"SIGNER:1": 7002}, pdf_sha256=hashlib.sha256(PDF).hexdigest())
    return services.approve_template_version(version.pk, env.template_owner, version.pdf_sha256)


INSERT = ("INSERT INTO agreements_agreementinstance (public_id, application_id, agreement_type_id, template_version_id,"
          " external_key, envelope_id, issue_status, signing_status, custody_status, created_at, updated_at)"
          " SELECT gen_random_uuid(), %s, t.id, %s, %s, %s, %s, %s, 'not_due', now(), now()"
          " FROM agreements_agreementtype t WHERE t.key = %s")


def test_p4_26_protections_hold_for_every_role(g, monkeypatch):
    app = issued(g, monkeypatch)
    instance = nda(app)
    recipient = instance.recipients.get()
    ua = ua_template(g)
    attempt = instance.attempts.first()
    roles = {role: g.committed.connect(role, autocommit=True) for role in ("app", "owner")}
    refused = (errors.InsufficientPrivilege, errors.RaiseException)
    draft = AgreementTemplateVersion.objects.create(  # an unapproved draft: content is fixed even before approval
        agreement_type=AgreementType.objects.get(key="nda"), version=2, provider_template_ref="envelope_template_nda2",
        provider_template_number=103, recipient_slots={"SIGNER:1": 7003}, pdf_sha256="0" * 64)
    for role, conn in roles.items():
        for sql, params in (
                ("UPDATE agreements_agreementrecipient SET email = 'x@example.test' WHERE id = %s", [recipient.pk]),
                ("DELETE FROM agreements_agreementrecipient WHERE id = %s", [recipient.pk]),
                ("TRUNCATE agreements_agreementrecipient CASCADE", []),
                ("INSERT INTO agreements_agreementrecipient (instance_id, role, signing_order, required, who, name, email)"
                 " VALUES (%s, 'SIGNER', 2, true, 'staff', 'x', 'x@example.test')", [instance.pk]),  # after the create
                ("UPDATE agreements_agreementtemplateversion SET pdf_sha256 = 'x' WHERE id = %s", [g.template.pk]),
                ("UPDATE agreements_agreementtemplateversion SET pdf_sha256 = 'x' WHERE id = %s", [draft.pk]),
                ("UPDATE agreements_agreementtemplateversion SET status = 'draft' WHERE id = %s", [g.template.pk]),
                ("DELETE FROM agreements_agreementtemplateversion WHERE id = %s", [g.template.pk]),
                ("INSERT INTO agreements_agreementtemplateversion (agreement_type_id, version, provider_template_ref,"
                 " provider_template_number, recipient_slots, pdf_sha256, status, approved_by, approved_at, created_at)"
                 " SELECT id, 9, 'envelope_x', 9, '{}', 'x', 'approved', 'user:1', now(), now()"
                 " FROM agreements_agreementtype WHERE key = 'nda'", []),  # born approved, bypassing the owner
                ("UPDATE agreements_agreementinstance SET envelope_id = 'envelope_other' WHERE id = %s", [instance.pk]),
                ("UPDATE agreements_agreementinstance SET agreement_type_id = agreement_type_id + 1 WHERE id = %s", [instance.pk]),
                ("UPDATE agreements_envelopeattempt SET external_key = 'ag_other' WHERE id = %s", [attempt.pk]),
                ("UPDATE agreements_agreementtype SET gate = 'signing' WHERE key = 'nda'", [])):
            if role == "owner" and sql.startswith(("UPDATE agreements_envelopeattempt", "UPDATE agreements_agreementtype")):
                continue  # column grants protect these from the application role; the owner runs migrations (ADR-14)
            with pytest.raises(refused):
                conn.execute(sql, params)
    EnvelopeAttempt.objects.create(instance=instance, step="create", external_key="ag_used_before", outcome="decided_not_sent")
    for conn in roles.values():  # a key is never reused (P4-D-19), for every role
        with pytest.raises(refused, match="never reused"):
            conn.execute("UPDATE agreements_agreementinstance SET external_key = 'ag_used_before' WHERE id = %s", [instance.pk])
    with pytest.raises(errors.InsufficientPrivilege):
        roles["app"].execute("DELETE FROM agreements_agreementinstance WHERE id = %s", [instance.pk])
    with pytest.raises(errors.UniqueViolation):  # one live instance per (application, type)
        roles["app"].execute(INSERT, [app.pk, g.template.pk, "ag_second", "", "create_pending", "not_started", "nda"])
    for params in ([app.pk, ua.pk, "ag_bad1", "", "create_pending", "signing_complete_verified", "user_agreement"],
                   [app.pk, ua.pk, "ag_bad2", "envelope_x", "create_pending", "not_started", "user_agreement"],
                   [app.pk, g.template.pk, "ag_bad3", "", "create_pending", "not_started", "user_agreement"],  # wrong type
                   [app.pk, draft.pk, "ag_bad4", "", "create_pending", "not_started", "nda"]):  # unapproved version
        with pytest.raises(errors.InsufficientPrivilege, match="agreement instance"):
            roles["app"].execute(INSERT, params)
    for conn in roles.values():  # D-15: no User Agreement before the NDA is signing_complete_verified
        with pytest.raises(errors.InsufficientPrivilege, match="D-15"):
            conn.execute(INSERT, [app.pk, ua.pk, f"ag_ua_{id(conn)}", "", "create_pending", "not_started", "user_agreement"])
    # Stated limit (021 section 15): the status columns are the application's to write until 4B.2 decides whether the
    # fresh read becomes database-visible. With the NDA verified, the backstop lets the User Agreement through.
    roles["app"].execute("UPDATE agreements_agreementinstance SET signing_status = 'signing_complete_verified' WHERE id = %s",
                         [instance.pk])
    roles["app"].execute(INSERT, [app.pk, ua.pk, "ag_ua_ok", "", "create_pending", "not_started", "user_agreement"])
    assert AgreementInstance.objects.filter(application=app, agreement_type__key="user_agreement").count() == 1


# --- TEST-P4-20, 28: guards and the hardened client ---------------------------------------------------------------

def test_p4_20_a_real_documenso_host_and_credentials_are_refused_outside_an_authorized_environment(settings):
    class Dev:
        CATALYST_ENV = "development"
        CATALYST_AGREEMENT_PROVIDER_URL = "https://sign.example.test/api/v2"
        CATALYST_AGREEMENT_PROVIDER_ADDRESS = ""
        CATALYST_AGREEMENT_PROVIDER_CA_FILE = ""
        CATALYST_AGREEMENT_PROVIDER_TOKEN = "api_synthetic"
    problems = guards.agreement_problems(Dev, {})
    assert any("PROVIDER_URL" in p for p in problems) and any("PROVIDER_TOKEN" in p for p in problems)
    assert guards.agreement_problems(type("S", (), {"CATALYST_ENV": "test"}), {"CATALYST_AGREEMENT_PROVIDER_TOKEN": "x"})

    class Test(Dev):
        CATALYST_ENV = "test"
        CATALYST_AGREEMENT_PROVIDER_ADDRESS = "203.0.113.5"  # not loopback
    assert any("loopback" in p for p in guards.agreement_problems(Test, {}))
    Test.CATALYST_AGREEMENT_PROVIDER_URL = "http://documenso.example.test/api/v2"
    assert any("https" in p for p in guards.agreement_problems(Test, {}))
    assert guards.provider_problems(settings.EMAIL_BACKEND, {"DOCUMENSO_API_KEY": "x"})  # provider names, as before
    assert settings.CATALYST_AGREEMENT_PROVIDER_URL == "" and not provider.configured()  # the code default
    with pytest.raises(provider.ProviderError, match="provider_not_configured"):
        provider.read("envelope_0001")


def test_p4_28_the_client_refuses_redirects_oversize_bad_tls_and_non_pdf(tls, settings):
    fake = FakeDocumenso(tls.documenso).start()
    try:
        configure(settings, fake, tls)
        fake.fault("GET /envelope/", ("redirect", "https://elsewhere.example.test/api/v2/envelope/x"), ("oversize",))
        for code in ("redirect_refused", "response_too_large"):
            with pytest.raises(provider.ProviderError, match=code) as raised:
                provider.read("envelope_0001")
            assert raised.value.unknown  # for a write this would be an unknown outcome
        assert len(fake.requests) == 2  # the redirect was never followed
        fake.download = (200, "text/html", b"<html>not a pdf</html>")
        with pytest.raises(provider.ProviderError, match="download_not_pdf"):
            provider.download("item_1")
        fake.download = (200, "application/pdf", PDF)
        assert provider.download("item_1") == PDF
        with pytest.raises(provider.ProviderError) as raised:
            provider.read("missing")
        assert raised.value.status == 404 and TOKEN not in repr(raised.value) + str(raised.value)
        settings.CATALYST_AGREEMENT_PROVIDER_ADDRESS = "127.0.0.2"  # the pinned address, where nothing listens
        with pytest.raises(provider.ProviderError) as raised:
            provider.read("envelope_0001")
        assert not raised.value.sent
    finally:
        fake.stop()
    other = FakeDocumenso(tls.untrusted).start()  # a certificate from an untrusted authority, for another name
    try:
        configure(settings, other, tls)
        with pytest.raises(provider.ProviderError, match="tls_certificate_refused") as raised:
            provider.read("envelope_0001")
        assert not raised.value.sent and not other.requests
    finally:
        other.stop()


def test_agreement_records_are_not_in_the_admin_and_fixtures_are_synthetic():
    from django.contrib import admin

    assert not any(m._meta.app_label == "agreements" for m in admin.site._registry)
    from pathlib import Path
    from tests import support
    text = Path(support.ROOT, "tests", "documenso_fake.py").read_text()
    assert "documenso.example.test" in text and "intentsolutions" not in text
    assert connection.vendor == "postgresql"
    assert AgreementRecipient.Role.SIGNER == "SIGNER"


# --- 4B.1 review: recovery paths, orphans, duplicates and the remaining clauses -----------------------------------

def expire_lease(env, kind, poison=False):
    env.committed.connect("owner", autocommit=True).execute(
        "UPDATE workflow_pendingaction SET lease_expires_at = now() - interval '1 second'"
        + (", attempts = max_attempts" if poison else "") + " WHERE kind = %s AND status = 'running'", [kind])


@pytest.mark.parametrize("poison", [False, True], ids=["lease_expired", "attempts_exhausted"])
@pytest.mark.parametrize("step", ["create", "distribute"])
def test_p4_03_12_a_crash_after_the_exchange_reconciles_and_never_sends_again(g, monkeypatch, step, poison):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    handler = handlers.CreateAgreement if step == "create" else handlers.DistributeAgreement
    path = "/envelope/use" if step == "create" else "/envelope/distribute"

    def crash(self, claim, result):  # the request reached the provider; the worker dies before recording it
        raise RuntimeError("synthetic crash")
    monkeypatch.setattr(handler, "after_call", crash)
    run_worker()
    action = PendingAction.objects.get(kind=f"{step}_agreement")
    assert action.status == "running" and len(g.fake.calls("POST", path)) == 1
    assert EnvelopeAttempt.objects.get(step=step).outcome == "sending"
    monkeypatch.setattr(handler, "after_call", lambda self, claim, result: None)
    expire_lease(g, f"{step}_agreement", poison)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert len(g.fake.calls("POST", path)) == 1  # never sent a second time
    assert instance.issue_status == "issued" and len(g.fake.envelopes) == 1
    assert EnvelopeAttempt.objects.get(step=step).outcome == "found_by_evidence"
    assert PendingAction.objects.filter(pk=action.pk, status="done", last_error="found_by_evidence").exists()


def test_p4_30_a_late_draft_orphan_is_recorded_left_and_kept_open_for_staff(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    old_key = instance.external_key
    services.decide_uncertain_create(instance.pk, g.agreement_decider, "not_sent")
    g.fake.add_envelope(template_ref=g.template.provider_template_ref, external_id=old_key,  # our creates are drafts
                        recipients=[{"id": 7001, "email": "ada@example.test"}])
    run_worker()
    cancel = EnvelopeAttempt.objects.get(step="cancel")
    assert (cancel.outcome, cancel.outcome_code) == ("not_sent", "left_draft")  # never recorded as cancelled
    assert not g.fake.calls("POST", "/envelope/cancel") and items(app, handlers.LATE_ORPHAN).count() == 1
    assert EnvelopeAttempt.objects.get(external_key=old_key, step="create").outcome == "orphan_found"


def test_p4_11_duplicate_envelopes_for_one_key_go_to_staff_and_block_a_new_create(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/use", ("drop_after",))
    real = provider.create_from_template

    def create(template_ref, external_key, recipients):
        try:
            return real(template_ref, external_key, recipients)
        finally:
            g.fake.add_envelope(template_ref=template_ref, external_id=external_key,
                                recipients=[{"id": 7001, "email": "ada@example.test"}])
    monkeypatch.setattr(provider, "create_from_template", create)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "create_uncertain" and not instance.envelope_id
    assert items(app, handlers.DUPLICATE_ENVELOPES).count() == 1 and not g.fake.calls("POST", "/envelope/distribute")
    with pytest.raises(services.Refused, match="duplicate_envelopes_open"):
        services.decide_uncertain_create(instance.pk, g.agreement_decider, "not_sent")


def test_p4_11_only_our_key_template_document_and_recipients_are_evidence():
    from types import SimpleNamespace

    class Recipients:
        def all(self):
            return [SimpleNamespace(email="Ada@Example.test")]
    instance = SimpleNamespace(recipients=Recipients(), template_version=SimpleNamespace(provider_template_number=101))
    ada = (provider.Recipient("ada@example.test", "SIGNER", 1, "NOT_SIGNED"),)
    good = provider.Envelope("envelope_1", "ag_k", "DRAFT", 101, "DOCUMENT", ada)
    assert handlers.matches(good, instance, "ag_k")
    for bad in (good.__class__("envelope_1", "ag_other", "DRAFT", 101, "DOCUMENT", ada),
                good.__class__("envelope_1", "ag_k", "DRAFT", 202, "DOCUMENT", ada),
                good.__class__("envelope_1", "ag_k", "DRAFT", 101, "TEMPLATE", ada),
                good.__class__("envelope_1", "ag_k", "DRAFT", 101, "DOCUMENT", ada + (provider.Recipient(
                    "extra@example.test", "SIGNER", 2, "NOT_SIGNED"),))):
        assert not handlers.matches(bad, instance, "ag_k")


def test_p4_18_distribute_honours_a_429_and_reconciles_a_5xx(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/distribute", ("status", 429, {"Retry-After": "nan"}), ("status", 503))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    attempts = list(instance.attempts.filter(step="distribute").order_by("id").values_list("outcome", "outcome_code"))
    assert attempts == [("not_sent", "rate_limited"), ("unknown", "http_503")]  # a 5xx may have acted: reconciled
    assert instance.issue_status == "distribute_uncertain" and items(app, handlers.DISTRIBUTE_UNKNOWN).count() == 1


def test_p4_22_reconciliation_runs_while_automation_is_paused(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    g.fake.fault("POST /envelope/use", ("drop_before",))

    def pause_now(self, claim, result):
        AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    monkeypatch.setattr(handlers.CreateAgreement, "after_call", pause_now)
    run_worker()
    assert AutomationPause.objects.exists()
    assert set(PendingAction.objects.filter(kind="reconcile_agreement").values_list("status", flat=True)) == {"done"}
    assert items(app, handlers.CREATE_UNKNOWN).count() == 1  # an unknown outcome is never parked by a pause


def test_p4_25_create_refuses_when_the_recipient_is_no_longer_the_verified_address(g, monkeypatch):
    from workflow import ledger

    app = admitted(g, monkeypatch)
    approve(g)
    activate()
    assert ledger.run_one()  # step 1 only: the instance and its recipient
    monkeypatch.setattr(handlers, "verified_address", lambda application: "changed@example.test")
    run_worker()
    assert not g.fake.requests and items(app, handlers.DISTRIBUTE_REFUSED).count() == 1


def test_p4_25_distribute_refuses_when_the_provider_recipients_differ(g, monkeypatch):
    app = admitted(g, monkeypatch)
    approve(g)
    activate()

    def add_recipient(self, claim, result):  # someone added a recipient in the provider's interface
        g.fake.envelopes[result]["recipients"].append({"email": "stranger@example.test", "role": "SIGNER",
                                                       "signingOrder": 2, "signingStatus": "NOT_SIGNED"})
    monkeypatch.setattr(handlers.CreateAgreement, "after_call", add_recipient)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "failed_needs_staff" and not g.fake.calls("POST", "/envelope/distribute")
    assert items(app, handlers.ENVELOPE_MISMATCH).count() == 1


def test_p4_28_the_client_bounds_time_encoding_truncation_and_its_own_configuration(tls, settings):
    fake = FakeDocumenso(tls.documenso).start()
    try:
        configure(settings, fake, tls)
        settings.CATALYST_AGREEMENT_DEADLINE_SECONDS = 1
        fake.fault("GET /envelope/", ("slow", 2), ("encoded",), ("truncated",))
        for code in ("deadline_exceeded|timeout", "content_encoding_refused", "response_truncated|connection_failed"):
            with pytest.raises(provider.ProviderError, match=code) as raised:
                provider.read("envelope_0001")
            assert raised.value.sent and raised.value.unknown
        settings.CATALYST_AGREEMENT_PROVIDER_CA_FILE = ""
        with pytest.raises(provider.ProviderError, match="provider_trust_store_missing"):
            provider.read("envelope_0001")
        settings.CATALYST_AGREEMENT_PROVIDER_CA_FILE = tls.ca
        settings.CATALYST_AGREEMENT_PROVIDER_ADDRESS = "203.0.113.5"
        with pytest.raises(provider.ProviderError, match="provider_address_not_pinned") as raised:
            provider.read("envelope_0001")
        assert not raised.value.sent
    finally:
        fake.stop()

    class Response:
        def __init__(self, value):
            self.value = value

        def getheader(self, name):
            return self.value
    assert provider._retry_after(Response("nan")) is None and provider._retry_after(Response("-5")) is None
    assert provider._retry_after(Response("999999")) == settings.CATALYST_AGREEMENT_RETRY_AFTER_MAX_SECONDS
    with pytest.raises(provider.ProviderError, match="response_unreadable"):
        provider.envelope({"id": "envelope 1; DROP", "recipients": []})
    assert provider.envelope({"id": "envelope_1", "status": "WEIRD", "recipients": []}).status == "UNKNOWN"


def test_p4_20_the_agreement_guard_is_wired_and_requires_a_test_host():
    import inspect

    assert "agreement_problems" in inspect.getsource(guards.all_problems)

    class Test:
        CATALYST_ENV = "test"
        CATALYST_AGREEMENT_PROVIDER_URL = "https://documenso.example.com/api/v2"
        CATALYST_AGREEMENT_PROVIDER_ADDRESS = "127.0.0.1"
    assert any(".test host" in p for p in guards.agreement_problems(Test, {}))
    Test.CATALYST_AGREEMENT_PROVIDER_URL = "https://documenso.example.test/api/v2"
    assert guards.agreement_problems(Test, {}) == []


def test_p4_09_the_command_needs_a_real_approval_reference():
    with pytest.raises(CommandError):
        call_command("activate_agreements", "--activation-version", "1", "--approval-ref", "   ", stdout=StringIO())
