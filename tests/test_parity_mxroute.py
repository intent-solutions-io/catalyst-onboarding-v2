"""First-generation parity for the mailbox (034 rows 37 to 39; bead catalyst-v2-bgl.10): the live MXroute adapter run
through a stub transport, the first-name username policy with the host-side collision check, and the one-time-password
welcome verified by an IMAP login against a scripted loopback server. Synthetic only: no socket leaves the box, no key,
`.test` addresses; the settings that would reach a real host are the ones the guards refuse outside test and staging.
"""

import logging
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.db import connection
from django.db.models.functions import Now

from applications.models import Application
from config import guards
from correspondence import outbound
from correspondence.models import ApprovedMessage, MessageTemplate, MessageTemplateVersion, StaffItem
from correspondence.rendering import canonical_digest
from correspondence.roles import TEMPLATE_OWNER
from provisioning import core, credentials, naming, password_welcome, services
from provisioning.adapter import AdapterError, Mailbox
from provisioning.models import AddressReservation, CredentialSetup, ProvisioningAttempt
from provisioning.mxroute import MXrouteHost, login_check
from tests.conftest import ModelNetworkRefused
from tests.imap_server import ScriptedIMAP
from tests.mxroute_stub import StubbedMXrouteHost
from tests.test_guards import staging
from tests.test_outbound import staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, approved, c, complete, d, ev, g, grant, h, issued, items, k, nda, of, p2, release,
    request_of, run_worker, sign_and_settle, tls,
)
from workflow.models import PendingAction

DOMAIN = "team.example.test"
KEY_VALUE = "synthetic-mxroute-key-0042"  # gitleaks:allow (synthetic; never a real credential)
LINK = re.compile(r"http://catalyst\.example\.test(/setup/[^/\s]+/)")


@pytest.fixture
def mx(k, settings, tmp_path):
    """`k` (agreements with custody) plus the live adapter over the stub transport, its settings at test values, the
    approver and two operators."""
    stub = StubbedMXrouteHost.transport
    stub.reset()
    key_file = tmp_path / "mxroute-key"
    key_file.write_text(KEY_VALUE + "\n")
    key_file.chmod(0o600)
    settings.CATALYST_PROVISIONING_ADAPTER = "tests.mxroute_stub.StubbedMXrouteHost"
    settings.CATALYST_PROVISIONING_DOMAIN = DOMAIN
    settings.CATALYST_PROVISIONING_API_URL = "https://api.mxroute.test"
    settings.CATALYST_PROVISIONING_API_SERVER = "synthetic-server"
    settings.CATALYST_PROVISIONING_API_ACCOUNT = "synthetic-account"
    settings.CATALYST_PROVISIONING_API_KEY_FILE = str(key_file)
    settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS = 0
    k.approver = grant(k, staff(k, "provisioning-approver"), "approve_provisioning")
    k.op1 = grant(k, staff(k, "provisioning-operator-1"), "operate_provisioning")
    k.op2 = grant(k, staff(k, "provisioning-operator-2"), "operate_provisioning")
    k.stub, k.key_file = stub, key_file
    yield k
    stub.reset()


@pytest.fixture
def otp(mx, settings, tls):
    """`mx` in one-time-password mode, with a TLS IMAP server on loopback the login check must satisfy."""
    imap = ScriptedIMAP(tls=tls.good).start()
    settings.CATALYST_MAIL_CA_FILE = tls.ca
    settings.CATALYST_PROVISIONING_IMAP_HOST = "127.0.0.1"
    settings.CATALYST_PROVISIONING_IMAP_PORT = imap.port
    settings.CATALYST_PROVISIONING_CREDENTIAL_MODE = "one_time_password"
    mx.imap = imap
    yield mx
    imap.stop()


def password_template(env, variables=("display_name", "mailbox_address", "mailbox_username", "password")):
    """A synthetic, approved version of the secret-bearing password welcome (the wording is bead bgl.11's)."""
    template, _ = MessageTemplate.objects.get_or_create(key=password_welcome.TEMPLATE, defaults={
        "purpose": "synthetic", "secret_bearing": True})
    subject = "Your mailbox"
    body = "Hello $display_name,\n\n" + "".join(f"{name}: ${name}\n" for name in variables if name != "display_name")
    version = MessageTemplateVersion.objects.create(
        template=template, version=template.versions.count() + 1, subject=subject, body_text=body,
        variables=list(variables), secret_bearing=True, content_sha256=canonical_digest(subject, body))
    outbound.approve_template_version(version.pk, staff(env, f"welcome-owner-{version.version}", TEMPLATE_OWNER))
    return version


def paths(stub, method=None):
    return [p for m, p in stub.calls if method is None or m == method]


def setups(request):
    return list(CredentialSetup.objects.filter(request=request).order_by("series").values_list("mode", "state"))


def nowhere_in_the_database(secret: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        for (table,) in cursor.fetchall():
            cursor.execute(f"SELECT count(*) FROM {table} WHERE row_to_json({table})::text LIKE %s", [f"%{secret}%"])
            assert cursor.fetchone()[0] == 0, table


# --- the adapter's contract (row 37) ------------------------------------------------------------------------------

def test_bgl10_the_adapter_speaks_the_documented_routes_with_the_three_headers_and_reads_the_key_from_its_file(mx):
    host = StubbedMXrouteHost()
    assert host.read(DOMAIN, "Ada") is None  # 404 is the one authoritative "absent"
    assert mx.stub.calls == [("GET", f"/domains/{DOMAIN}/email-accounts/ada")]
    assert mx.stub.headers_seen[0] == {"X-Server": "synthetic-server", "X-Username": "synthetic-account",
                                       "X-API-Key": KEY_VALUE, "Accept": "application/json"}
    host.create(DOMAIN, "ada", "Synthetic-Pw-1", 1024, 100)
    assert mx.stub.calls[-1] == ("POST", f"/domains/{DOMAIN}/email-accounts")
    assert mx.stub.bodies[-1] == {"username": "ada", "password": "Synthetic-Pw-1", "quota": 1024, "limit": 100}
    assert host.read(DOMAIN, "ada") == Mailbox("ada", DOMAIN, 1024, 100, False)
    host.set_password(DOMAIN, "ada", "Synthetic-Pw-2")
    assert mx.stub.calls[-1] == ("PATCH", f"/domains/{DOMAIN}/email-accounts/ada")
    assert mx.stub.bodies[-1] == {"password": "Synthetic-Pw-2"}  # the password only: quota and limit stay
    mx.stub.forwarders[(DOMAIN, "sales")] = ("ada@example.test",)
    mx.stub.catch_all[DOMAIN] = "catch@team.example.test"
    assert host.list_forwarders(DOMAIN) == [("sales", ("ada@example.test",))]
    assert host.read_catch_all(DOMAIN) == "catch@team.example.test"
    host.delete_forwarder(DOMAIN, "sales")
    host.delete_forwarder(DOMAIN, "sales")  # already gone: met, not an error
    assert paths(mx.stub)[-4:] == [f"/domains/{DOMAIN}/forwarders", f"/domains/{DOMAIN}/catch-all",
                                   f"/domains/{DOMAIN}/forwarders/sales", f"/domains/{DOMAIN}/forwarders/sales"]
    assert not hasattr(host, "delete") and not hasattr(host, "suspend")  # no mailbox delete or suspend exists (P5-D-9)
    before = len(mx.stub.calls)
    for call, code in ((lambda: host.read("other.example.test", "ada"), "domain_not_allowed"),
                       (lambda: host.read(DOMAIN, "../reseller"), "local_part_invalid"),
                       (lambda: host.set_password(DOMAIN, "a..b", "x" * 12), "local_part_invalid")):
        with pytest.raises(AdapterError, match=code) as caught:
            call()
        assert caught.value.sent is False
    assert len(mx.stub.calls) == before  # nothing left for a refused route


def test_bgl10_a_missing_or_empty_key_file_refuses_before_any_call_and_the_key_never_appears_in_an_error(mx, settings):
    host = StubbedMXrouteHost()
    mx.key_file.write_text("\n")
    with pytest.raises(AdapterError, match="mail_host_credential_empty"):
        host.read(DOMAIN, "ada")
    mx.key_file.unlink()
    with pytest.raises(AdapterError, match="mail_host_credential_unreadable") as caught:
        host.read(DOMAIN, "ada")
    assert caught.value.sent is False and not mx.stub.calls
    assert KEY_VALUE not in repr(caught.value) and KEY_VALUE not in str(caught.value)
    settings.CATALYST_PROVISIONING_API_URL = ""
    with pytest.raises(AdapterError, match="mail_host_not_configured"):
        host.read(DOMAIN, "ada")
    settings.CATALYST_PROVISIONING_API_URL = "http://api.mxroute.test"  # plain http off loopback: refused by the adapter too
    with pytest.raises(AdapterError, match="mail_host_url_not_https"):
        host.read(DOMAIN, "ada")
    assert not mx.stub.calls


def test_bgl10_the_adapter_maps_answers_to_the_p4_error_taxonomy(mx):
    host = StubbedMXrouteHost()
    mx.stub.faults.append(("GET", "500"))
    with pytest.raises(AdapterError, match="server_error") as caught:
        host.read(DOMAIN, "ada")  # a failed or ambiguous lookup is unknown, never "absent"
    assert caught.value.unknown and caught.value.status == 500
    mx.stub.faults.append(("POST", "connect_refused"))
    with pytest.raises(AdapterError, match="connecterror") as caught:
        host.create(DOMAIN, "ada", "Synthetic-Pw-1", 1024, 100)
    assert caught.value.sent is False and not caught.value.unknown and (DOMAIN, "ada") not in mx.stub.mailboxes
    mx.stub.faults.append(("POST", "timeout_after_send"))
    with pytest.raises(AdapterError, match="readtimeout") as caught:
        host.create(DOMAIN, "ada", "Synthetic-Pw-1", 1024, 100)
    assert caught.value.sent and caught.value.unknown and (DOMAIN, "ada") in mx.stub.mailboxes  # it landed
    with pytest.raises(AdapterError, match="conflict") as caught:
        host.create(DOMAIN, "ada", "Synthetic-Pw-1", 1024, 100)
    assert caught.value.conflict and caught.value.status == 409 and not caught.value.unknown
    mx.stub.faults.append(("POST", "429"))
    with pytest.raises(AdapterError, match="rate_limited") as caught:
        host.create(DOMAIN, "bob", "Synthetic-Pw-1", 1024, 100)
    assert caught.value.unknown and caught.value.retry_after == 1.0  # throttled after it landed: a read decides
    mx.stub.faults.append(("PATCH", "400"))
    with pytest.raises(AdapterError, match="validation_error") as caught:
        host.set_password(DOMAIN, "ada", "Synthetic-Pw-2")
    assert caught.value.status == 400 and not caught.value.unknown  # the one definite password rejection (023 11.8)
    with pytest.raises(AdapterError, match="not_found") as caught:
        host.set_password(DOMAIN, "nobody", "Synthetic-Pw-2")
    assert caught.value.status == 404 and not caught.value.unknown
    assert all("Synthetic-Pw" not in repr(c) for c in [caught.value])


def test_bgl10_the_default_transport_is_the_covered_http_client_and_opens_nothing_in_tests(mx):
    with pytest.raises(ModelNetworkRefused):  # the suite's raising transport covers httpx2, so the default path is proven
        MXrouteHost().read(DOMAIN, "ada")   # to be that client and can never reach a network from a test
    assert not mx.stub.calls


def test_bgl10_the_login_check_verifies_the_certificate_and_tells_a_refusal_from_a_failure(settings, tls):
    accepted = ScriptedIMAP(tls=tls.good).start()
    refusing = ScriptedIMAP(tls=tls.good, login_reply="NO").start()
    untrusted = ScriptedIMAP(tls=tls.untrusted).start()
    plaintext = ScriptedIMAP(tls=None).start()
    try:
        settings.CATALYST_MAIL_CA_FILE = tls.ca
        settings.CATALYST_PROVISIONING_IMAP_HOST = ""
        with pytest.raises(AdapterError, match="imap_not_configured"):
            login_check("ada@team.example.test", "Synthetic-Pw-1")
        settings.CATALYST_PROVISIONING_IMAP_HOST = "127.0.0.1"
        settings.CATALYST_PROVISIONING_IMAP_PORT = accepted.port
        assert login_check("ada@team.example.test", "Synthetic-Pw-1") is True and accepted.logins == 1
        assert "LOGOUT" in accepted.commands and not {"SELECT", "EXAMINE", "UID FETCH"} & set(accepted.commands)
        settings.CATALYST_PROVISIONING_IMAP_PORT = refusing.port
        assert login_check("ada@team.example.test", "Synthetic-Pw-1") is False  # the server's answer, not a failure
        for server, code in ((untrusted, "imap_tls_refused"), (plaintext, "imap_")):
            settings.CATALYST_PROVISIONING_IMAP_PORT = server.port
            with pytest.raises(AdapterError, match=code) as caught:
                login_check("ada@team.example.test", "Synthetic-Pw-1")
            assert caught.value.sent is False and server.logins == 0  # no credential reaches an unverified peer
    finally:
        for server in (accepted, refusing, untrusted, plaintext):
            server.stop()


# --- the adapter under the P5 handlers: create, refuse, continue (row 37) ----------------------------------------

def test_bgl10_create_when_absent_reads_then_posts_then_reads_again_and_the_password_is_in_no_record(mx, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    app, request = approved(mx, monkeypatch)
    run_worker()
    assert [m for m, _ in mx.stub.calls] == ["GET", "POST", "GET"]
    assert all(p.startswith(f"/domains/{DOMAIN}/email-accounts") for p in paths(mx.stub))
    request.refresh_from_db()
    assert request.status == "setup_pending" and mx.stub.mailboxes[(DOMAIN, "ada.example")]["quota"] == 1024
    password = mx.stub.passwords_seen[0]
    assert len(password) >= 32
    nowhere_in_the_database(password)
    assert password not in caplog.text and KEY_VALUE not in caplog.text
    audited = [r.getMessage() for r in caplog.records if r.name == "provisioning.mxroute"]
    assert len(audited) == 3 and all("ada.example" not in line and "/domains/" not in line for line in audited)  # 023 11.8
    assert all(KEY_VALUE not in (e or "") for e in PendingAction.objects.values_list("last_error", flat=True))


def test_bgl10_a_mailbox_present_and_not_ours_is_refused_with_a_staff_item_and_never_changed(mx, monkeypatch):
    app, request = approved(mx, monkeypatch)
    mx.stub.mailboxes[(DOMAIN, "ada.example")] = {"quota": 1024, "limit": 100, "suspended": False}
    run_worker()
    request.refresh_from_db()
    assert request.status == "conflict" and items(app, core.ITEM_CONFLICT).count() == 1
    assert [m for m, _ in mx.stub.calls] == ["GET"]  # read before create: nothing was sent
    services.supersede(request.pk, mx.op1, "Someone else's mailbox: a new address will be chosen")
    run_worker()
    assert [m for m, _ in mx.stub.calls] == ["GET"]  # nothing of ours may exist there: no watch, and never a write
    assert "current_password" not in mx.stub.mailboxes[(DOMAIN, "ada.example")]
    assert AddressReservation.objects.get(pk=request.reservation_id).released_at is not None


def test_bgl10_a_crashed_create_finds_its_own_mailbox_on_the_next_run_and_never_posts_twice(mx, monkeypatch):
    from provisioning import handlers

    app, request = approved(mx, monkeypatch)
    crashed = []

    def crash(self, claim):
        if not crashed:
            crashed.append(1)
            raise RuntimeError("synthetic: the worker stopped before recording")
    monkeypatch.setattr(handlers.CreateMailbox, "after_call", crash)
    run_worker()
    action = PendingAction.objects.get(kind="provision_create")
    assert action.status == "running" and ProvisioningAttempt.objects.get().outcome == "sending"
    PendingAction.objects.filter(pk=action.pk).update(lease_expires_at=Now() - timedelta(seconds=1))
    run_worker()  # the second run: no second POST; the reconcile read finds the first run's mailbox
    assert [m for m, _ in mx.stub.calls].count("POST") == 1
    request.refresh_from_db()
    assert request.status == "found_by_evidence" and items(app, core.ITEM_CONFIRM_FOUND).count() == 1  # 023 11.3
    services.confirm_found_mailbox(request.pk, mx.op1, "ours", "Read matches our request exactly")
    run_worker()
    request.refresh_from_db()
    assert request.status == "setup_pending" and [m for m, _ in mx.stub.calls].count("POST") == 1


def test_bgl10_a_lost_answer_after_the_create_landed_continues_by_reading_never_by_a_second_post(mx, monkeypatch):
    app, request = approved(mx, monkeypatch)
    mx.stub.faults.append(("POST", "timeout_after_send"))
    run_worker()
    request.refresh_from_db()
    assert request.status == "found_by_evidence" and [m for m, _ in mx.stub.calls].count("POST") == 1
    assert ProvisioningAttempt.objects.get().absent_before is True  # the absent read is the evidence it is ours
    services.confirm_found_mailbox(request.pk, mx.op1, "ours", "Read matches our request exactly")
    run_worker()
    request.refresh_from_db()
    assert request.status == "setup_pending"


def test_bgl10_a_connection_refused_before_sending_is_retried_never_called_a_rejection(mx, monkeypatch):
    app, request = approved(mx, monkeypatch)
    mx.stub.faults.append(("POST", "connect_refused"))
    run_worker()
    outcomes = list(ProvisioningAttempt.objects.filter(step="create").order_by("id").values_list("outcome", "code"))
    assert outcomes == [("not_created", "create_not_sent_connecterror"), ("succeeded", "")]
    assert [m for m, _ in mx.stub.calls].count("POST") == 2 and not ProvisioningAttempt.objects.filter(outcome="rejected").exists()
    request.refresh_from_db()
    assert request.status == "setup_pending" and not items(app, core.ITEM_FAILED).exists()


# --- the username policy (row 38) ---------------------------------------------------------------------------------

def test_bgl10_the_first_name_policy_folds_names_and_orders_eleven_candidates(settings):
    assert naming.parts("José Núñez García") == ("jose", "garcia")
    assert naming.parts("Synthetic-Lovelace") == ("syntheticlovelace", "")
    assert naming.parts("  O'Brien   de la   Cruz ") == ("obrien", "cruz")
    assert naming.parts("李 小龙") == ("", "") and naming.parts("") == ("", "")
    assert naming.parts("A" * 40 + " B" * 1) == ("a" * 30, "b")  # capped so first.last9 fits a local part
    assert naming.first_name_candidates("Ada Example") == ["ada", "ada.example"] + [f"ada.example{n}" for n in range(2, 10)]
    assert naming.first_name_candidates("Cher") == ["cher"] + [f"cher{n}" for n in range(2, 10)]
    assert naming.first_name_candidates("李 小龙") is None
    assert all(naming.SAFE.fullmatch(c) for c in naming.first_name_candidates("Ada-Marie Example-Smith"))
    settings.CATALYST_PROVISIONING_NAMING_POLICY = "first_last"
    assert naming.candidates_for("Ada Example")[:3] == ["ada.example", "ada.example2", "ada.example3"]
    assert naming.candidates_for("Cher") is None
    settings.CATALYST_PROVISIONING_NAMING_POLICY = "first_name"
    assert naming.candidates_for("Ada Example")[:2] == ["ada", "ada.example"]
    assert naming.candidates_for("Cher")[:2] == ["cher", "cher2"]
    assert naming.candidates_for("Ada Example", policy="first_last")[0] == "ada.example"
    settings.CATALYST_PROVISIONING_RESERVED_PREFIXES = ["no-reply", "Support"]  # the owner's prefixes (row 38)
    assert naming.reserved("support.team") and naming.reserved("noreply2") and naming.reserved("no.reply.desk")
    assert naming.reserved("supportive") and not naming.reserved("ada.support") and not naming.reserved("ada")
    settings.CATALYST_PROVISIONING_RESERVED_PREFIXES = []  # the code default: exact names and role addresses only
    assert not naming.reserved("support.team") and naming.reserved("support")


def test_bgl10_the_first_name_policy_skips_names_taken_at_the_host_up_to_the_ninth_suffix(mx, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_NAMING_POLICY = "first_name"
    settings.CATALYST_PROVISIONING_NAMING_HOST_CHECK = True
    app = complete(mx, monkeypatch)
    assert release()["released"] == 1
    assert request_of(app).reservation.local_part == "ada"  # the first name alone, as the live population prefers
    assert {m for m, _ in mx.stub.calls} == {"GET"} and f"/domains/{DOMAIN}/forwarders" in paths(mx.stub)
    assert not any(p.endswith("/email-accounts") for p in paths(mx.stub))  # reads only, no create before approval
    services.supersede(request_of(app).pk, mx.op1, "Synthetic: choose again against a fuller population")
    mx.stub.calls.clear()
    mx.stub.forwarders[(DOMAIN, "ada")] = ("owner@example.test",)  # a forwarder alias shadows the first name
    mx.stub.mailboxes[(DOMAIN, "ada.example")] = {"quota": 1, "limit": 1}
    for n in range(2, 9):
        mx.stub.mailboxes[(DOMAIN, f"ada.example{n}")] = {"quota": 1, "limit": 1}
    assert release()["released"] == 1
    assert request_of(app).reservation.local_part == "ada.example9"  # the ninth suffix is the last one tried
    assert [m for m, _ in mx.stub.calls].count("POST") == 0
    services.supersede(request_of(app).pk, mx.op1, "Synthetic: now every candidate is taken")
    mx.stub.mailboxes[(DOMAIN, "ada.example9")] = {"quota": 1, "limit": 1}
    assert release()["name_needs_review"] == 1 and items(app, core.ITEM_NAME_REVIEW).count() == 1  # then a person
    assert not AddressReservation.objects.filter(application=app, released_at__isnull=True).exists()


def test_bgl10_the_first_name_policy_skips_reserved_role_and_held_addresses_without_reading_the_host(mx, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_NAMING_POLICY = "first_name"
    settings.CATALYST_PROVISIONING_RESERVED_LOCAL_PARTS = ["ada", "ada.example"]  # the owner's reserved list
    app = complete(mx, monkeypatch)
    assert release()["released"] == 1
    assert request_of(app).reservation.local_part == "ada.example2" and not mx.stub.calls  # the database collisions only
    services.supersede(request_of(app).pk, mx.op1, "Synthetic: a role word as the first name")
    Application.objects.filter(pk=app.pk).update(display_name="Info Example")
    assert release()["released"] == 1
    assert request_of(app).reservation.local_part == "info.example" and not mx.stub.calls  # "info" is a role address
    services.supersede(request_of(app).pk, mx.op1, "Synthetic: a reserved prefix covers every candidate")
    settings.CATALYST_PROVISIONING_RESERVED_PREFIXES = ["info"]
    assert release()["name_needs_review"] == 1 and items(app, core.ITEM_NAME_REVIEW).count() == 1  # then a person


def test_bgl10_the_default_policy_without_the_host_check_proposes_as_before_and_reads_nothing(mx, monkeypatch):
    app = complete(mx, monkeypatch)
    mx.stub.mailboxes[(DOMAIN, "ada.example")] = {"quota": 1, "limit": 1}  # unseen until the create's own read
    assert release()["released"] == 1
    assert request_of(app).reservation.local_part == "ada.example" and not mx.stub.calls  # P5-D-1, unchanged


def test_bgl10_a_host_that_cannot_answer_the_collision_check_leaves_the_handoff_held(mx, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_NAMING_HOST_CHECK = True
    app = complete(mx, monkeypatch)
    mx.stub.faults.append(("GET", "500"))
    assert release() == {"dry_run": False, "host_read_server_error": 1, "released": 0}
    assert not AddressReservation.objects.exists() and PendingAction.objects.get(kind="provision").status == "held"
    assert items(app, core.ITEM_BLOCKED).count() == 1
    assert release()["released"] == 1 and request_of(app).reservation.local_part == "ada.example"  # answered: proposed


# --- the one-time-password welcome (row 39) -----------------------------------------------------------------------

def test_bgl10_the_one_time_password_welcome_sets_checks_by_imap_then_sends_to_the_personal_address_only(otp, monkeypatch, caplog,
                                                                                                         settings):
    caplog.set_level(logging.DEBUG)
    # bgl.6 (parity integration): the welcome carries the configured sender's display name and Reply-To
    settings.CATALYST_FROM_DISPLAY_NAME, settings.CATALYST_REPLY_TO = "Synthetic Agreements", "agreements-synthetic@example.test"
    password_template(otp)
    app, request = approved(otp, monkeypatch)
    sent_before, welcomes_before = len(mail.outbox), len(otp.server.messages)
    run_worker()
    assert [m for m, _ in otp.stub.calls] == ["GET", "POST", "GET", "PATCH"]
    assert otp.imap.logins == 1
    password = otp.stub.passwords_seen[-1]  # the PATCH's, generated inside the exchange
    assert password != otp.stub.passwords_seen[0] and len(password) == 20 and password.isalnum()
    assert otp.stub.mailboxes[(DOMAIN, "ada.example")]["current_password"] == password
    assert len(mail.outbox) == sent_before + 1
    welcome = mail.outbox[-1]
    assert welcome.to == ["ada@example.test"] and not welcome.cc and not welcome.bcc  # the verified personal address only
    assert welcome.from_email == f"Synthetic Agreements <{settings.DEFAULT_FROM_EMAIL}>"
    assert welcome.reply_to == ["agreements-synthetic@example.test"]
    assert f"password: {password}" in welcome.body and "mailbox_username: ada.example" in welcome.body
    assert f"mailbox_address: ada.example@{DOMAIN}" in welcome.body
    assert setups(request) == [("one_time_password", "completed")]
    app.refresh_from_db()
    request.refresh_from_db()
    assert app.stage == "active" and request.status == "active"
    assert len(otp.server.messages) == welcomes_before  # no second welcome through the P2 sender
    assert not ApprovedMessage.objects.filter(kind="welcome").exists()  # nothing frozen carries the credential
    assert app.events.filter(kind="provisioning_welcome_password_sent").exists()
    assert app.events.get(kind="provisioning_activated").data["welcome"] == "sent_with_password"
    nowhere_in_the_database(password)  # TEST-P5-15's rule holds for the generated password too
    assert password not in caplog.text and KEY_VALUE not in caplog.text
    assert PendingAction.objects.filter(kind=credentials.INVITE).count() == 0  # no link was ever sent in this mode


def test_bgl10_a_refused_imap_login_sends_no_welcome_and_each_new_round_sets_a_new_password(otp, monkeypatch, settings):
    settings.CATALYST_SETUP_INVITE_MAX_SERIES = 2
    password_template(otp)
    otp.imap.login_reply = "NO"
    app, request = approved(otp, monkeypatch)
    sent_before = len(mail.outbox)
    run_worker()
    assert len(mail.outbox) == sent_before  # nothing went out: the credential was never shown to work
    assert setups(request) == [("one_time_password", "superseded")] * 2  # bounded, then staff
    assert otp.imap.logins == 2 and [m for m, _ in otp.stub.calls].count("PATCH") == 2
    first, second = otp.stub.passwords_seen[-2:]
    assert first != second  # never replayed: each round sets a new password
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").count() == 1
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    assert app.events.filter(kind="provisioning_setup_superseded", data__code="login_check_failed").count() == 2


def test_bgl10_an_unknown_password_set_sends_nothing_checks_nothing_and_the_next_round_succeeds(otp, monkeypatch):
    password_template(otp)
    otp.stub.faults.append(("PATCH", "timeout_after_send"))
    app, request = approved(otp, monkeypatch)
    sent_before = len(mail.outbox)
    run_worker()
    assert setups(request) == [("one_time_password", "superseded"), ("one_time_password", "completed")]
    assert otp.imap.logins == 1 and [m for m, _ in otp.stub.calls].count("PATCH") == 2
    lost, used = otp.stub.passwords_seen[-2:]
    assert lost != used and len(mail.outbox) == sent_before + 1
    assert used in mail.outbox[-1].body and lost not in mail.outbox[-1].body  # only a password proven to work is sent
    assert Application.objects.get(pk=app.pk).stage == "active"


def test_bgl10_an_uncertain_welcome_send_is_never_repeated_with_the_same_password(otp, monkeypatch, settings):
    settings.CATALYST_SETUP_INVITE_MAX_SERIES = 1
    password_template(otp)

    class Unanswered(password_welcome.EmailMessage):
        def send(self, fail_silently=False):
            raise ConnectionError("synthetic: the sink did not answer")
    monkeypatch.setattr(password_welcome, "EmailMessage", Unanswered)
    app, request = approved(otp, monkeypatch)
    run_worker()
    assert setups(request) == [("one_time_password", "superseded")]
    assert [m for m, _ in otp.stub.calls].count("PATCH") == 1 and otp.imap.logins == 1
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").exists()
    assert app.events.filter(kind="provisioning_setup_superseded", data__code="welcome_send_uncertain").exists()


def test_bgl10_without_a_usable_password_template_nothing_is_set_and_staff_are_told(otp, monkeypatch):
    app, request = approved(otp, monkeypatch)
    run_worker()
    assert setups(request) == [("one_time_password", "cancelled")]
    assert [m for m, _ in otp.stub.calls].count("PATCH") == 0 and otp.imap.logins == 0
    assert app.events.filter(kind="provisioning_welcome_password_refused",
                             data__reason="no_approved_password_welcome_template").exists()
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").count() == 1
    password_template(otp, variables=("display_name", "mailbox_address"))  # approved, but it could not carry the password
    credentials.reissue(request.pk, otp.op1, "Template approved; sending the welcome now")
    run_worker()
    assert setups(request)[-1] == ("one_time_password", "cancelled") and otp.stub.passwords_seen[1:] == []
    assert app.events.filter(kind="provisioning_welcome_password_refused",
                             data__reason="welcome_template_lacks_password").exists()
    assert Application.objects.get(pk=app.pk).stage == "provisioning"


def test_bgl10_a_crash_during_the_exchange_is_never_replayed_and_the_sweep_covers_a_round_that_never_returns(otp, monkeypatch, settings):
    password_template(otp)
    app, request = approved(otp, monkeypatch)
    crashed = []
    real = password_welcome.SendPasswordWelcome._exchange

    def crash(self, setup, version):
        if not crashed:
            crashed.append(1)
            raise RuntimeError("synthetic: the worker stopped after the set")
        return real(self, setup, version)
    monkeypatch.setattr(password_welcome.SendPasswordWelcome, "_exchange", crash)
    run_worker()
    action = PendingAction.objects.get(kind=credentials.OTP_WELCOME)
    assert action.status == "running" and setups(request) == [("one_time_password", "set_pending")]
    PendingAction.objects.filter(pk=action.pk).update(lease_expires_at=Now() - timedelta(seconds=1))
    run_worker()  # the earlier exchange's outcome is unknown: superseded, and a new round runs with a new password
    assert setups(request) == [("one_time_password", "superseded"), ("one_time_password", "completed")]
    assert Application.objects.get(pk=app.pk).stage == "active"


def test_bgl10_the_link_flow_and_its_records_are_untouched_when_the_mode_stays_default(mx, monkeypatch):
    from tests.test_credentials import welcome_template

    welcome_template(mx)
    app, request = approved(mx, monkeypatch)
    run_worker()
    assert setups(request) == [("set_your_own", "invited")] and LINK.search(mail.outbox[-1].body)
    assert [m for m, _ in mx.stub.calls] == ["GET", "POST", "GET"]  # no password set by the worker in P5-D-6's flow
    assert app.events.get(kind="provisioning_setup_opened").data["mode"] == "set_your_own"


def test_bgl10_the_mode_of_a_series_is_fixed_for_every_role(otp, monkeypatch):
    from psycopg import errors

    password_template(otp)
    app, request = approved(otp, monkeypatch)
    run_worker()
    setup = CredentialSetup.objects.get(request=request)
    for role in ("app", "owner"):
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            otp.committed.connect(role, autocommit=True).execute(
                "UPDATE provisioning_credentialsetup SET mode = 'set_your_own' WHERE id = %s", [setup.pk])


def test_bgl10_closing_the_application_cancels_a_queued_password_welcome_before_any_password_is_set(otp, monkeypatch):
    from datetime import timedelta as delta

    from provisioning import closure

    password_template(otp)
    closer = grant(otp, staff(otp, "application-closer"), "close_application")
    enqueue = core.enqueue

    def later(kind, request, key, **kwargs):  # hold the welcome back so the worker goes idle with it still queued
        if kind == credentials.OTP_WELCOME:
            kwargs["due_in"] = delta(days=1)
        return enqueue(kind, request, key, **kwargs)

    monkeypatch.setattr(core, "enqueue", later)
    app, request = approved(otp, monkeypatch)
    run_worker()
    welcome = PendingAction.objects.get(kind=credentials.OTP_WELCOME)
    assert welcome.status == "queued" and setups(request) == [("one_time_password", "invitation_pending")]
    closure.close_application(app.pk, closer, "closed", "Programme ended for this applicant")
    welcome.refresh_from_db()
    assert (welcome.status, welcome.last_error) == ("cancelled", "application_closed")
    assert setups(request) == [("one_time_password", "cancelled")]
    assert "PATCH" not in {m for m, _ in otp.stub.calls} and not otp.stub.passwords_seen[1:]  # only the create's


def test_bgl10_the_password_generator_is_strong_and_within_the_documented_bounds():
    seen = {password_welcome.generate_password() for _ in range(50)}
    assert len(seen) == 50
    for password in seen:
        assert len(password) == 20 and password.isalnum() and password.isascii()
        assert any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password)
    assert password_welcome.template_problem(None) == "no_approved_password_welcome_template"


# --- the guards (rows 37 to 39 stay disabled outside test and staging) --------------------------------------------

def test_bgl10_live_host_settings_are_refused_outside_test_and_staging_and_bounded_inside(settings):
    from types import SimpleNamespace

    live = dict(CATALYST_PROVISIONING_API_URL="https://api.mxroute.test", CATALYST_PROVISIONING_API_SERVER="s",
                CATALYST_PROVISIONING_API_ACCOUNT="a", CATALYST_PROVISIONING_API_KEY_FILE="/run/secrets/mxroute-key",
                CATALYST_PROVISIONING_IMAP_HOST="127.0.0.1")
    production = SimpleNamespace(CATALYST_ENV="production", CATALYST_PUBLIC_BASE_URL="https://x.test", **live)
    problems = guards.provisioning_problems(production, {})
    assert sum("allowed only in the test and staging environments" in p for p in problems) == len(live)
    environ = {name: "x" for name in live}
    assert sum("may not be set from the environment" in p for p in guards.provisioning_problems(production, environ)) == len(live)
    assert guards.provisioning_problems(staging(**live), {}) == []
    for change, expected in (({"CATALYST_PROVISIONING_API_URL": "https://api.mxroute.com"}, ".test host"),
                             ({"CATALYST_PROVISIONING_API_URL": "http://api.mxroute.test"}, "https"),
                             ({"CATALYST_PROVISIONING_API_URL": "https://api.mxroute.test/v1?x=1"}, "origin"),
                             ({"CATALYST_PROVISIONING_API_URL": "https://user@api.mxroute.test"}, "origin"),
                             ({"CATALYST_PROVISIONING_API_KEY_FILE": "relative/key"}, "absolute"),
                             ({"CATALYST_PROVISIONING_IMAP_HOST": "imap.example.com"}, "loopback or a .test host"),
                             ({"CATALYST_PROVISIONING_IMAP_PORT": 0}, "port number"),
                             ({"CATALYST_PROVISIONING_NAMING_POLICY": "nickname"}, "first_last or first_name"),
                             ({"CATALYST_PROVISIONING_CREDENTIAL_MODE": "emailed"}, "set_your_own or one_time_password"),
                             ({"CATALYST_PROVISIONING_ADAPTER": "provisioning.mxroute.MXrouteHost"}, "test fake")):
        found = guards.provisioning_problems(staging(**{**live, **change}), {})
        assert any(expected in p for p in found), (change, found)
    assert guards.provisioning_problems(staging(**{**live, "CATALYST_PROVISIONING_API_URL": "http://127.0.0.1:8443"}), {}) == []
    assert guards.provisioning_problems(staging(**{**live, "CATALYST_PROVISIONING_IMAP_HOST": "imap.staging.test"}), {}) == []
    # The shipped defaults are the P5 ones: the two parity switches off and every live-host value empty.
    assert (settings.CATALYST_PROVISIONING_NAMING_POLICY, settings.CATALYST_PROVISIONING_NAMING_HOST_CHECK,
            settings.CATALYST_PROVISIONING_CREDENTIAL_MODE) == ("first_last", False, "set_your_own")
    assert not any(getattr(settings, name) for name in guards.PROVISIONING_TEST_ONLY[2:])
