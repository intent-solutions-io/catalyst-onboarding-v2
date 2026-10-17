"""P4 task 4B.2: webhooks as hints, observations, the reconciliation sweep, completion verification, the D-15 sequence,
decline, expiry, cancellation at the provider and withdrawal during agreements (021 sections 4 to 6; D-39).
TEST-P4-01, 02, 06, 08, 13 to 16, 18 (reads), 22 to 24, 29, 31, 32.

Everything runs against the local fake Documenso; webhooks are posted to the test-mounted route by the Django test
client, shaped like the installed version's (021 section 15).
"""

import dataclasses
import importlib
import json
import logging

import pytest
from django.test import Client
from django.utils import timezone

from agreements import completion, provider, services
from agreements.models import AgreementInstance, ProviderObservation
from applications.models import Application
from correspondence.models import StaffItem
from tests.test_agreements import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, activate, approve, c, d, ev, g, grant, issued, nda, p2, run_worker, tls, ua_template,
)
from workflow.models import AutomationPause, PendingAction

SECRET = "synthetic-webhook-secret"
HOOK = "/hooks/documenso/"


@pytest.fixture
def h(g, settings):
    """`g` plus a webhook secret, the decider's management permission, and a User Agreement template."""
    settings.CATALYST_AGREEMENT_WEBHOOK_SECRETS = [SECRET]
    grant(g, g.agreement_decider, "manage_agreements")
    g.fake.template(ref="envelope_template_ua", number=102, slot=7002)
    g.ua = ua_template(g)
    return g


def post(body, secret=SECRET, **extra):
    headers = {"HTTP_X_DOCUMENSO_SECRET": secret} if secret is not None else {}
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return Client().post(HOOK, data=data, content_type="application/json", **headers, **extra)


def reads_now():
    """Bring queued reads forward (the sweep interval and the minimum interval are minutes long) and run them."""
    PendingAction.objects.filter(kind="read_agreement", status="queued").update(due_at=timezone.now())
    run_worker()


def items(app, reason):
    return StaffItem.objects.filter(application=app, reason_code=reason, status="open")


def signing_gate(env, key="nda"):
    """The custody gate (P4-D-6) arrives with 4B.3; the sequence is tested with the NDA gated on signing alone."""
    env.committed.connect("owner", autocommit=True).execute(
        "UPDATE agreements_agreementtype SET gate = 'signing' WHERE key = %s", [key])


def reset_gate(env):
    env.committed.connect("owner", autocommit=True).execute(
        "UPDATE agreements_agreementtype SET gate = 'signing_and_custody'")


# --- TEST-P4-13, 02: webhooks are hints; only a fresh read verifies ---------------------------------------------

def test_p4_13_02_a_webhook_never_verifies_and_duplicates_and_late_events_are_harmless(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.sign(instance.envelope_id)
    body = h.fake.webhook(instance.envelope_id)
    assert post(body).status_code == 200  # the worker has not run: the webhook alone
    instance.refresh_from_db()
    assert instance.signing_status == "signing_complete_observed"  # a hint, never verified
    assert post(body).status_code == 200 and post(body).status_code == 200  # replays
    assert ProviderObservation.objects.filter(instance=instance, source="webhook").count() == 1
    reads_now()
    instance.refresh_from_db()
    assert instance.signing_status == "signing_complete_verified" and instance.custody_status == "pending"
    read = ProviderObservation.objects.get(instance=instance, source="read", envelope_status="COMPLETED")
    assert read.identity_match and read.recipients_match and read.all_required_signed
    late = h.fake.webhook(instance.envelope_id, "DOCUMENT_SENT")
    late["payload"]["status"] = "PENDING"  # an older event arriving last
    assert post(late).status_code == 200
    reads_now()
    assert nda(Application.objects.get(pk=app.pk)).signing_status == "signing_complete_verified"


# --- TEST-P4-08, 23, 24: authentication, flooding, and nothing kept that should not be ----------------------------

def test_p4_08_webhook_authentication_and_uniform_answers(h, monkeypatch, settings):
    app = issued(h, monkeypatch)
    instance = nda(app)
    body = h.fake.webhook(instance.envelope_id)
    for secret in (None, "", "wrong", SECRET + "x"):
        assert post(body, secret=secret).status_code == 401
    assert not ProviderObservation.objects.filter(source="webhook").exists()
    settings.CATALYST_AGREEMENT_WEBHOOK_SECRETS = ["old-secret", SECRET]  # a rotation: both valid (P4-D-17)
    assert post(body, secret="old-secret").status_code == 200 and post(body).status_code == 200
    unknown = json.loads(json.dumps(body))
    unknown["payload"]["externalId"] = "ag_not_ours"
    known, foreign = post(body), post(unknown)
    assert (known.status_code, known.content) == (foreign.status_code, foreign.content) == (200, b"")  # nothing revealed
    assert post(b"not json").status_code == 200
    settings.CATALYST_AGREEMENT_WEBHOOK_SECRETS = []  # none configured: nothing authenticates
    assert post(body).status_code == 401
    assert Client().get(HOOK).status_code == 405


def test_p4_08_the_route_is_mounted_only_in_test_and_development(settings):
    from django.urls import clear_url_caches

    import config.urls
    try:
        settings.CATALYST_ENV = "staging"
        importlib.reload(config.urls)
        assert not any("documenso" in str(p.pattern) for p in config.urls.urlpatterns)
    finally:
        settings.CATALYST_ENV = "test"
        importlib.reload(config.urls)
        clear_url_caches()
    assert any("documenso" in str(p.pattern) for p in config.urls.urlpatterns)


def test_p4_23_24_a_webhook_flood_makes_one_read_and_keeps_no_body_or_token(h, monkeypatch, caplog, settings):
    caplog.set_level(logging.DEBUG)
    app = issued(h, monkeypatch)
    instance = nda(app)
    body = h.fake.webhook(instance.envelope_id, "DOCUMENT_OPENED")
    for i in range(50):
        body["createdAt"] = f"flood-{i}"
        assert post(body).status_code == 200
    assert PendingAction.objects.filter(kind="read_agreement", status__in=("queued", "running")).count() == 1
    gets = len(h.fake.calls("GET", f"/envelope/{instance.envelope_id}"))
    reads_now()
    assert len(h.fake.calls("GET", f"/envelope/{instance.envelope_id}")) == gets + 1  # fifty hints, one read
    for i in range(20):  # more hints after the read: the next read waits for the minimum interval
        body["createdAt"] = f"again-{i}"
        post(body)
    nxt = PendingAction.objects.get(kind="read_agreement", status="queued")
    last = ProviderObservation.objects.filter(instance=instance, source="read").latest("observed_at").observed_at
    assert (nxt.due_at - last).total_seconds() >= settings.CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS - 1
    big = json.dumps(body) + " " * settings.CATALYST_AGREEMENT_WEBHOOK_MAX_BYTES
    assert post(big).status_code == 413
    owner = h.committed.connect("owner", autocommit=True)
    for (table,) in owner.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall():
        dump = str(owner.execute(f"SELECT * FROM {table}").fetchall())  # noqa: S608 (catalogue names)
        assert "secret-signing-token" not in dump and "flood-" not in dump, table
    assert "secret-signing-token" not in caplog.text and SECRET not in caplog.text and "flood-" not in caplog.text


# --- TEST-P4-14, 15, 16: the sweep and what a read shows -----------------------------------------------------------

def test_p4_14_a_lost_webhook_is_caught_by_the_sweep(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    sweep = PendingAction.objects.get(kind="read_agreement", status="queued")
    assert (sweep.due_at - timezone.now()).total_seconds() > 60  # scheduled at issue, at the sweep interval
    h.fake.sign(instance.envelope_id)  # no webhook arrives
    reads_now()
    assert nda(Application.objects.get(pk=app.pk)).signing_status == "signing_complete_verified"


@pytest.mark.parametrize("what,signing,reason", [
    ("partial", "partially_signed", None), ("reject", "declined", "agreement_declined"),
    ("expire", "expired", "agreement_expired"), ("cancel", "cancelled", "agreement_cancelled_at_provider")])
def test_p4_15_partial_rejection_expiry_and_cancellation(h, monkeypatch, what, signing, reason):
    app = issued(h, monkeypatch)
    instance = nda(app)
    env = h.fake.envelopes[instance.envelope_id]
    if what == "partial":
        h.fake.sign(instance.envelope_id, complete=False)
    elif what == "reject":
        h.fake.reject(instance.envelope_id)
    elif what == "expire":
        h.fake.expire(instance.envelope_id)
    else:
        env["status"] = "CANCELLED"  # cancelled in the provider's interface, not by us
    post(h.fake.webhook(instance.envelope_id, "DOCUMENT_SIGNED"))
    reads_now()
    instance.refresh_from_db()
    assert instance.signing_status == signing
    if reason:
        assert items(app, reason).count() == 1
    assert AutomationPause.objects.filter(subject_id=app.public_ref).exists() == (what == "reject")  # P4-D-9
    assert not AgreementInstance.objects.filter(application=app, agreement_type__key="user_agreement").exists()


@pytest.mark.parametrize("field,value", [("externalId", "ag_someone_else"), ("templateId", 999), ("id", "envelope_9999")])
def test_p4_16_a_read_showing_another_envelope_key_or_template_never_verifies(h, monkeypatch, field, value):
    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.sign(instance.envelope_id)
    real = provider.read

    def read(envelope_id):
        env = real(envelope_id)
        changes = {"externalId": "external_id", "templateId": "template_number", "id": "id"}
        return dataclasses.replace(env, **{changes[field]: value})
    monkeypatch.setattr(provider, "read", read)
    reads_now()
    instance.refresh_from_db()
    assert instance.signing_status == "not_started" and items(app, "agreement_envelope_mismatch").count() == 1


# --- TEST-P4-01, 06, 31: the D-15 sequence and the fresh read at the gate ----------------------------------------------

def test_p4_01_06_the_user_agreement_waits_for_the_ndas_gate(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    assert not AgreementInstance.objects.filter(application=app, agreement_type__key="user_agreement").exists()
    h.fake.sign(instance.envelope_id)
    reads_now()  # verified, but the NDA's gate also needs custody (P4-D-6, 4B.3): nothing more is issued
    assert nda(Application.objects.get(pk=app.pk)).signing_status == "signing_complete_verified"
    assert not AgreementInstance.objects.filter(application=app, agreement_type__key="user_agreement").exists()
    assert not h.fake.calls("POST", "/envelope/use")[1:]
    signing_gate(h)
    try:
        completion.enqueue_advance(Application.objects.get(pk=app.pk))
        run_worker()
        ua = AgreementInstance.objects.get(application=app, agreement_type__key="user_agreement")
        assert ua.issue_status == "issued" and ua.template_version == h.ua
        gate_reads = h.fake.calls("GET", f"/envelope/{instance.envelope_id}")
        assert len(gate_reads) >= 2  # the NDA was re-read at the moment the User Agreement was issued
    finally:
        reset_gate(h)


def test_p4_31_a_stale_verification_or_changed_recipients_never_advance(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    signing_gate(h)
    try:
        h.fake.sign(instance.envelope_id)
        real, calls = provider.read, {"n": 0}

        def read(envelope_id):
            env = real(envelope_id)
            calls["n"] += 1
            if calls["n"] >= 2:  # by the gate's fresh read, someone was added in the provider's interface
                extra = provider.Recipient("stranger@example.test", "SIGNER", 2, "SIGNED")
                return dataclasses.replace(env, recipients=env.recipients + (extra,))
            return env
        monkeypatch.setattr(provider, "read", read)
        reads_now()
        assert nda(Application.objects.get(pk=app.pk)).signing_status == "signing_complete_verified"
        assert not AgreementInstance.objects.filter(application=app, agreement_type__key="user_agreement").exists()
        assert items(app, "agreement_recipients_changed").count() == 1
    finally:
        reset_gate(h)


def test_p4_31_completion_with_changed_recipients_is_never_verified(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.envelopes[instance.envelope_id]["recipients"].append(
        {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
    h.fake.sign(instance.envelope_id)
    reads_now()
    instance.refresh_from_db()
    assert instance.signing_status == "signing_complete_observed" and items(app, "agreement_recipients_changed").count() == 1


# --- TEST-P4-29, 32: cancellation at the provider, reissue and withdrawal ----------------------------------------------

def test_p4_29_cancel_is_reconciled_at_the_provider_and_a_later_completion_goes_to_staff(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.fault("POST /envelope/cancel", ("drop_after",))  # cancelled at the provider, the answer lost
    services.cancel_agreement(instance.pk, h.agreement_decider)
    run_worker()
    instance.refresh_from_db()
    assert (instance.issue_status, instance.signing_status) == ("cancelled", "cancelled")
    assert h.fake.envelopes[instance.envelope_id]["status"] == "CANCELLED"
    assert instance.attempts.get(step="cancel").outcome == "found_by_evidence"
    assert len(h.fake.calls("POST", "/envelope/cancel")) == 1
    h.fake.envelopes[instance.envelope_id]["status"] = "COMPLETED"  # the provider later shows it signed
    post(h.fake.webhook(instance.envelope_id))
    reads_now()
    instance.refresh_from_db()
    assert instance.signing_status == "cancelled" and items(app, "agreement_completed_after_cancel").count() == 1
    new = services.reissue_agreement(instance.pk, h.agreement_decider)  # a decision-maker reissues (P4-D-9)
    run_worker()
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "superseded"
    new.refresh_from_db()
    assert new.issue_status == "issued" and new.external_key != instance.external_key


def test_p4_15_a_declined_agreement_is_reissued_only_by_a_decision_maker(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.reject(instance.envelope_id)
    reads_now()
    with pytest.raises(services.PermissionDenied):
        services.reissue_agreement(instance.pk, h.decider)
    new = services.reissue_agreement(instance.pk, h.agreement_decider)
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "superseded"
    AutomationPause.objects.filter(subject_id=app.public_ref).delete()  # staff resume after deciding
    run_worker()
    assert AgreementInstance.objects.get(pk=new.pk).issue_status == "issued"


def test_p4_32_withdrawal_during_agreements_cancels_every_live_envelope_and_issues_nothing_more(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    signing_gate(h)
    try:
        assert services.stop_agreements(app.pk, h.agreement_decider, "withdrawn") == ["cancel_pending"]
        run_worker()
        instance.refresh_from_db()
        assert instance.issue_status == "cancelled" and h.fake.envelopes[instance.envelope_id]["status"] == "CANCELLED"
        completion.enqueue_advance(Application.objects.get(pk=app.pk))
        run_worker()
        assert AgreementInstance.objects.filter(application=app).count() == 1
        assert len(h.fake.calls("POST", "/envelope/use")) == 1
        with pytest.raises(services.Refused, match="agreements_not_open"):
            services.reissue_agreement(instance.pk, h.agreement_decider)
    finally:
        reset_gate(h)


def test_p4_32_stopping_before_the_envelope_exists_watches_an_unknown_create(h, monkeypatch):
    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    h.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "create_uncertain"
    assert services.stop_agreements(app.pk, h.agreement_decider, "closed") == ["cancelled"]
    run_worker()
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "cancelled"
    assert instance.attempts.get(step="create").outcome == "abandoned"
    assert PendingAction.objects.filter(kind="reconcile_agreement", idempotency_key__contains=":watch:").exists()


def test_p4_12_an_unknown_distribute_can_be_decided_and_redistributed(h, monkeypatch):
    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    h.fake.fault("POST /envelope/distribute", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "distribute_uncertain"
    services.decide_uncertain_distribute(instance.pk, h.agreement_decider, "redistribute")
    run_worker()
    instance.refresh_from_db()
    assert instance.issue_status == "issued" and h.fake.envelopes[instance.envelope_id]["status"] == "PENDING"
    assert len(h.fake.calls("POST", "/envelope/distribute")) == 2  # the first never reached the provider
    assert not items(app, "agreement_distribute_unknown").exists()


# --- TEST-P4-18 (reads), 22: rate limits, an unavailable provider, and a pause ------------------------------------------

def test_p4_18_reads_honour_a_429_and_a_down_provider_goes_to_staff(h, monkeypatch, settings):
    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.fault("GET /envelope/", ("status", 429, {"Retry-After": "120"}))
    reads_now()
    read = PendingAction.objects.get(kind="read_agreement", status="queued")
    assert read.last_error == "rate_limited" and (read.due_at - timezone.now()).total_seconds() > 100
    settings.CATALYST_AGREEMENT_PROVIDER_URL = "https://documenso.example.test:9/api/v2"
    reads_now()
    assert PendingAction.objects.get(pk=read.pk).status == "failed"
    assert items(app, "agreement_provider_unavailable").count() == 1
    assert nda(app).signing_status == "not_started" and instance.issue_status == "issued"


def test_p4_22_a_pause_holds_reads_and_resume_makes_one_read_not_a_burst(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    pause = AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic",
                                           actor_ref="t")
    h.fake.sign(instance.envelope_id)
    gets = len(h.fake.calls("GET", f"/envelope/{instance.envelope_id}"))
    for _ in range(10):
        post(h.fake.webhook(instance.envelope_id))
    reads_now()
    assert len(h.fake.calls("GET", f"/envelope/{instance.envelope_id}")) == gets  # nothing read while paused
    pause.delete()
    reads_now()
    assert len(h.fake.calls("GET", f"/envelope/{instance.envelope_id}")) == gets + 1
    assert nda(Application.objects.get(pk=app.pk)).signing_status == "signing_complete_verified"


def test_p4_20_webhook_secrets_are_test_only_and_at_most_two():
    from config import guards

    class Dev:
        CATALYST_ENV = "development"
        CATALYST_AGREEMENT_WEBHOOK_SECRETS = ["x"]
    assert any("WEBHOOK_SECRETS" in p for p in guards.agreement_problems(Dev, {}))
    assert guards.agreement_problems(type("T", (), {"CATALYST_ENV": "test"}), {"CATALYST_AGREEMENT_WEBHOOK_SECRETS": "x"})

    class Test:
        CATALYST_ENV = "test"
        CATALYST_AGREEMENT_WEBHOOK_SECRETS = ["a", "b", "c"]
    assert any("two" in p for p in guards.agreement_problems(Test, {}))
