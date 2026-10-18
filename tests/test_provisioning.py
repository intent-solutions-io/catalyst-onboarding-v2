"""P5 task 5B.1: approved provisioning against a local fake mail host (023 sections 3 to 5 and 11; D-47).
TEST-P5-01, 02, 06 to 12 and 23. Synthetic only: the fake implements the documented MXroute mailbox operations in
process; no key, no network, `example.test` addresses.
"""

import json
from io import StringIO

import pytest
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import connection
from psycopg import errors

from applications.models import Application
from config import guards
from correspondence.models import StaffItem
from provisioning import core, naming, services
from provisioning.models import AddressReservation, ProvisioningAttempt, ProvisioningEvidence, ProvisioningRequest
from tests.mxroute_fake import FakeMailHost
from tests.test_agreement_custody import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, issued, k, nda, of, p2, run_worker, sign_and_settle, tls,
)
from tests.test_outbound import staff
from workflow.models import PendingAction

REFUSED = (errors.InsufficientPrivilege, errors.RaiseException)


@pytest.fixture
def pv(k, settings):
    """`k` (agreements with custody) plus the fake mail host, a `.test` domain, no settle grace, the approver (the
    owner's named grant, P5-D-3) and two provisioning operators."""
    FakeMailHost.reset()
    settings.CATALYST_PROVISIONING_ADAPTER = "tests.mxroute_fake.FakeMailHost"
    settings.CATALYST_PROVISIONING_DOMAIN = "example.test"
    settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS = 0
    k.approver = grant(k, staff(k, "provisioning-approver"), "approve_provisioning")
    k.op1 = grant(k, staff(k, "provisioning-operator-1"), "operate_provisioning")
    k.op2 = grant(k, staff(k, "provisioning-operator-2"), "operate_provisioning")
    yield k
    FakeMailHost.reset()


def complete(env, monkeypatch):
    """An applicant whose agreements are complete, with the held `provision` hand-off (P4)."""
    app = issued(env, monkeypatch)
    sign_and_settle(env, app, "nda")
    sign_and_settle(env, app, "user_agreement")
    app = Application.objects.get(pk=app.pk)
    assert app.stage == "agreements_complete" and PendingAction.objects.get(kind="provision").status == "held"
    return app


def AgreementInstanceLive(app):
    return [of(app, key).get() for key in ("nda", "user_agreement")]


def release() -> dict:
    out = StringIO()
    call_command("activate_provisioning", "--activation-version", "1", "--approval-ref", "D-47", stdout=out)
    return json.loads(out.getvalue())


def request_of(app) -> ProvisioningRequest:
    return ProvisioningRequest.objects.select_related("reservation").get(application=app, status__in=(
        "awaiting_approval", "approved", "create_pending", "create_uncertain", "found_by_evidence", "created",
        "verify_uncertain", "verified", "conflict", "failed_needs_staff"))


def items(app, reason):
    return StaffItem.objects.filter(application=app, reason_code=reason, status="open")


def approved(env, monkeypatch, settings=None):
    app = complete(env, monkeypatch)
    assert release()["released"] == 1
    request = request_of(app)
    services.approve(request.pk, env.approver, request.approval_digest)
    return app, request_of(app)


# --- TEST-P5-01, 02: release ------------------------------------------------------------------------------------

def test_p5_01_release_reads_afresh_and_creates_one_request_awaiting_the_approver(pv, monkeypatch):
    from agreements import provider

    app = complete(pv, monkeypatch)
    reads, real_read = [], provider.read
    monkeypatch.setattr(provider, "read", lambda envelope_id: reads.append(envelope_id) or real_read(envelope_id))
    assert release() == {"dry_run": False, "released": 1}
    assert sorted(reads) == sorted(i.envelope_id for i in AgreementInstanceLive(app))  # a fresh read of each
    request = request_of(app)
    assert request.status == "awaiting_approval" and request.reservation.address == "ada.example@example.test"
    assert (request.quota_mb, request.send_limit, request.method) == (1024, 100, "api")  # synthetic defaults (P5-D-2)
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    assert PendingAction.objects.get(kind="provision").status == "done"
    assert release() == {"dry_run": False, "released": 0}  # nothing held is left; a second run changes nothing
    assert ProvisioningRequest.objects.count() == 1 and not FakeMailHost.calls  # no mail-host call before approval


def test_p5_02_a_changed_agreement_at_the_provider_refuses_release_and_holds_reliance(pv, monkeypatch):
    app = complete(pv, monkeypatch)
    instance = of(app, "nda").get()
    pv.fake.envelopes[instance.envelope_id]["recipients"].append(
        {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
    assert release() == {"agreement_integrity_hold": 1, "dry_run": False, "released": 0}
    assert not ProvisioningRequest.objects.exists() and PendingAction.objects.get(kind="provision").status == "held"
    assert StaffItem.objects.filter(application=app, reason_code="agreement_integrity_hold", status="open").exists()


def test_p5_02_a_changed_prerequisite_after_approval_blocks_the_create_at_the_effect_boundary(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    instance = of(app, "nda").get()
    pv.fake.envelopes[instance.envelope_id]["recipients"].append(
        {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
    run_worker()
    request.refresh_from_db()
    assert request.status == "failed_needs_staff" and items(app, core.ITEM_BLOCKED).count() == 1
    assert not FakeMailHost.calls  # nothing reached the mail host


# --- TEST-P5-06: naming -----------------------------------------------------------------------------------------

def test_p5_06_the_naming_rule_is_deterministic_and_refuses_role_and_unsafe_addresses(settings):
    assert naming.proposal("Ada Example") == "ada.example"
    assert naming.proposal("José Núñez García") == "jose.garcia"
    assert naming.proposal("Cher") is None and naming.proposal("李 小龙") is None  # needs a reviewed exception
    for bad, code in (("postmaster", "local_part_reserved"), ("no-reply", "local_part_reserved"),
                      ("a..b", "local_part_invalid"), ("-x", "local_part_invalid"), ("x@y", "local_part_invalid")):
        with pytest.raises(naming.NamingRefused, match=code):
            naming.check(bad)
    settings.CATALYST_PROVISIONING_RESERVED_LOCAL_PARTS = ["founder"]
    with pytest.raises(naming.NamingRefused, match="local_part_reserved"):
        naming.check("Founder")


def test_p5_06_a_collision_takes_the_next_suffix_and_an_exception_needs_review(pv, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_RESERVED_LOCAL_PARTS = ["ada.example"]
    app = complete(pv, monkeypatch)
    release()
    assert request_of(app).reservation.local_part == "ada.example2"
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError, match="reservation_live_address_unique"), transaction.atomic():
        AddressReservation.objects.create(application=app, local_part="ada.example2", domain="Example.TEST",
                                          basis="naming_rule")  # never someone else's: unique on the normalized address


def test_p5_06_a_name_the_rule_cannot_form_waits_for_a_reviewed_exception(pv, monkeypatch):
    app = complete(pv, monkeypatch)
    Application.objects.filter(pk=app.pk).update(display_name="Cher")
    assert release()["name_needs_review"] == 1 and items(app, core.ITEM_NAME_REVIEW).count() == 1
    with pytest.raises(PermissionDenied):
        services.reserve_exception(app.pk, "cher", pv.op1, "Preferred professional name, one part")
    with pytest.raises(services.Refused, match="local_part_reserved"):
        services.reserve_exception(app.pk, "admin", pv.approver, "Preferred professional name, one part")
    services.reserve_exception(app.pk, "cher", pv.approver, "Preferred professional name, one part")
    assert not items(app, core.ITEM_NAME_REVIEW).exists()
    assert release()["released"] == 1 and request_of(app).reservation.basis == "reviewed_exception"


# --- TEST-P5-07: approval ---------------------------------------------------------------------------------------

def test_p5_07_approval_binds_the_exact_address_limits_method_and_prerequisites(pv, monkeypatch):
    app = complete(pv, monkeypatch)
    release()
    request = request_of(app)
    for user in (pv.op1, staff(pv, "root-provisioning", superuser=True)):
        with pytest.raises(PermissionDenied):
            services.approve(request.pk, user, request.approval_digest)
    with pytest.raises(services.Refused, match="changed_since_shown"):
        services.approve(request.pk, pv.approver, "0" * 64)
    assert request.approval_digest == core.approval_digest("ada.example@example.test", 1024, 100, "api",
                                                           request.prerequisite_digest)
    services.approve(request.pk, pv.approver, request.approval_digest)
    request.refresh_from_db()
    assert request.status == "approved" and request.approved_by == f"user:{pv.approver.pk}"
    assert PendingAction.objects.filter(kind="provision_create").count() == 1
    with pytest.raises(services.Refused, match="not_awaiting_approval"):  # a second approval changes nothing
        services.approve(request.pk, pv.approver, request.approval_digest)


# --- TEST-P5-08, 09, 12: create, reconcile, verify ---------------------------------------------------------------

def test_p5_08_12_the_attempt_is_committed_then_an_absent_read_then_one_create_then_an_authoritative_read(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    seen = {}
    real_create = FakeMailHost.create

    def create(self, *args):
        seen["attempt"] = list(ProvisioningAttempt.objects.values_list("outcome", "absent_before"))
        return real_create(self, *args)
    monkeypatch.setattr(FakeMailHost, "create", create)
    run_worker()
    assert seen["attempt"] == [("sending", True)]  # committed and the absent read recorded before the call
    assert [c[0] for c in FakeMailHost.calls] == ["read", "create", "read"]
    request.refresh_from_db()
    assert request.status == "verified"
    evidence = ProvisioningEvidence.objects.get(request=request)
    assert evidence.kind == "adapter_read" and evidence.facts["quota_mb"] == 1024 and not evidence.facts["suspended"]
    password = FakeMailHost.passwords_seen[0]
    with connection.cursor() as cursor:  # the generated password is in no record (023 11.8)
        for table in ("provisioning_provisioningrequest", "provisioning_provisioningattempt",
                      "provisioning_provisioningevidence", "workflow_pendingaction", "applications_applicationevent"):
            cursor.execute(f"SELECT count(*) FROM {table} WHERE row_to_json({table})::text LIKE %s", [f"%{password}%"])
            assert cursor.fetchone()[0] == 0, table


def test_p5_09_an_unknown_create_is_reconciled_by_reading_and_staff_confirm_it_is_ours(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    request.refresh_from_db()
    assert request.status == "found_by_evidence" and items(app, core.ITEM_CONFIRM_FOUND).count() == 1
    assert [c[0] for c in FakeMailHost.calls].count("create") == 1  # never called again blindly
    with pytest.raises(PermissionDenied):
        services.confirm_found_mailbox(request.pk, pv.approver, "ours", "Read matches our request exactly")
    services.confirm_found_mailbox(request.pk, pv.op1, "ours", "Read matches our request exactly")
    run_worker()
    request.refresh_from_db()
    assert request.status == "verified" and not items(app, core.ITEM_CONFIRM_FOUND).exists()


def test_p5_09_an_unknown_create_that_never_landed_runs_a_new_series_after_the_bounded_checks(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_lost")
    run_worker()
    request.refresh_from_db()
    attempts = list(ProvisioningAttempt.objects.filter(step="create").order_by("id").values_list("series", "outcome"))
    assert attempts == [(0, "not_created"), (1, "succeeded")] and request.status == "verified"


def test_p5_09_a_500_on_the_reconcile_read_is_unknown_never_absent(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.extend(["create_unknown", "read_500_after_create"])
    run_worker()
    assert "read_500_after_create" not in FakeMailHost.faults  # the 500 fired on the reconcile read
    assert not ProvisioningAttempt.objects.filter(outcome="not_created").exists()
    request.refresh_from_db()
    assert request.status == "found_by_evidence"  # the retried read decided; the 500 never counted as absent


def test_p5_09_a_mailbox_present_before_our_create_is_a_conflict_and_never_adopted(pv, monkeypatch):
    from provisioning.adapter import Mailbox

    app, request = approved(pv, monkeypatch)
    FakeMailHost.mailboxes[("example.test", "ada.example")] = Mailbox("ada.example", "example.test", 1024, 100, False)
    run_worker()
    request.refresh_from_db()
    assert request.status == "conflict" and items(app, core.ITEM_CONFLICT).count() == 1
    assert [c[0] for c in FakeMailHost.calls] == ["read"]  # no create was sent


def test_p5_10_a_mailbox_created_by_someone_else_inside_the_window_is_a_conflict(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_appears_first")
    run_worker()
    request.refresh_from_db()
    assert request.status == "conflict"
    assert ProvisioningAttempt.objects.get().outcome == "conflict"


def test_p5_10_a_duplicate_create_action_never_creates_a_second_mailbox(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    core.enqueue(core.CREATE, request, f"{core.CREATE}:{request.public_id}:duplicate")
    run_worker()
    assert [c[0] for c in FakeMailHost.calls].count("create") == 1
    assert ProvisioningAttempt.objects.filter(step="create").count() == 1


def test_p5_08_a_crash_after_the_exchange_is_reconciled_never_resent(pv, monkeypatch):
    from provisioning import handlers

    app, request = approved(pv, monkeypatch)
    crashed = []

    def crash(self, claim):
        if not crashed:
            crashed.append(1)
            raise RuntimeError("synthetic: the worker stopped before recording")
    monkeypatch.setattr(handlers.CreateMailbox, "after_call", crash)
    run_worker()
    action = PendingAction.objects.get(kind="provision_create")
    assert action.status == "running" and ProvisioningAttempt.objects.get().outcome == "sending"
    from django.db.models.functions import Now
    from datetime import timedelta
    PendingAction.objects.filter(pk=action.pk).update(lease_expires_at=Now() - timedelta(seconds=1))
    run_worker()
    assert [c[0] for c in FakeMailHost.calls].count("create") == 1
    request.refresh_from_db()
    assert request.status == "found_by_evidence"  # reconciled; staff confirm before verification


# --- TEST-P5-11: the checklist path -----------------------------------------------------------------------------

def test_p5_11_the_checklist_verifier_must_differ_from_the_creator_for_every_role(pv, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_METHOD = "checklist"
    app, request = approved(pv, monkeypatch)
    assert request.method == "checklist" and items(app, core.ITEM_CHECKLIST).count() == 1
    assert not PendingAction.objects.filter(kind="provision_create").exists() and not FakeMailHost.calls
    services.record_checklist_creation(request.pk, pv.op1, "Created in the panel with the approved limits")
    with pytest.raises(services.Refused, match="verifier_must_differ_from_creator"):
        services.attest_checklist_verification(request.pk, pv.op1, "Listed in the panel with the limits")
    from django.db import transaction

    with pytest.raises(Exception, match="verifier must differ") as caught, transaction.atomic():  # the database too
        ProvisioningEvidence.objects.create(request=request, kind="checklist_attested", actor_ref=f"user:{pv.op1.pk}")
    assert isinstance(caught.value.__cause__, errors.InsufficientPrivilege)
    services.attest_checklist_verification(request.pk, pv.op2, "Listed in the panel with the limits")
    request.refresh_from_db()
    assert request.status == "verified" and not items(app, core.ITEM_CHECKLIST).exists()


# --- supersession and the watch (023 11.11) ---------------------------------------------------------------------

def test_p5_superseding_a_request_without_a_mailbox_releases_the_address_and_awaits_a_new_approval(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    instance = of(app, "nda").get()
    pv.fake.envelopes[instance.envelope_id]["recipients"].append(
        {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
    run_worker()
    with pytest.raises(services.Refused, match="reason_needed"):
        services.supersede(request.pk, pv.op1, "x")
    services.supersede(request.pk, pv.op1, "The agreement changed at the provider")
    request.refresh_from_db()
    assert request.status == "superseded"
    assert AddressReservation.objects.get(pk=request.reservation_id).released_at is not None
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"
    assert PendingAction.objects.filter(kind="provision", status="held").count() == 1


def test_p5_superseding_after_a_mailbox_may_exist_keeps_the_address_and_watches_for_a_late_mailbox(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    request.refresh_from_db()
    assert request.status == "found_by_evidence"
    services.confirm_found_mailbox(request.pk, pv.op1, "conflict", "Not provably the one we requested")
    services.supersede(request.pk, pv.op1, "A new address will be chosen")
    assert AddressReservation.objects.get(pk=request.reservation_id).released_at is None  # held while watched
    run_worker()
    assert items(app, core.ITEM_LATE_MAILBOX).count() == 1  # the mailbox is there: rotate and revoke (5B.3), no delete


# --- protections and TEST-P5-23 ---------------------------------------------------------------------------------

def test_p5_records_are_fixed_for_every_role(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    run_worker()
    for role in ("app", "owner"):
        conn = pv.committed.connect(role, autocommit=True)
        for sql in ("UPDATE provisioning_provisioningrequest SET quota_mb = 0 WHERE id = %s",
                    "UPDATE provisioning_provisioningrequest SET approved_by = 'user:0' WHERE id = %s",
                    "UPDATE provisioning_provisioningrequest SET prerequisite_digest = 'x' WHERE id = %s",
                    "DELETE FROM provisioning_provisioningrequest WHERE id = %s"):
            with pytest.raises(REFUSED + (errors.CheckViolation,)):
                conn.execute(sql, [request.pk])
        evidence = ProvisioningEvidence.objects.filter(request=request).first()
        with pytest.raises(REFUSED):
            conn.execute("UPDATE provisioning_provisioningevidence SET note = 'x' WHERE id = %s", [evidence.pk])
        attempt = ProvisioningAttempt.objects.filter(request=request).first()
        with pytest.raises(REFUSED):
            conn.execute("UPDATE provisioning_provisioningattempt SET outcome = 'unknown' WHERE id = %s", [attempt.pk])
        with pytest.raises(REFUSED):
            conn.execute("TRUNCATE provisioning_provisioningevidence")


def test_p5_23_a_real_adapter_domain_or_environment_value_is_refused(settings):
    settings.CATALYST_PROVISIONING_ADAPTER = "provisioning.live.MXroute"
    settings.CATALYST_PROVISIONING_DOMAIN = "intentsolutions.io"
    problems = guards.provisioning_problems(settings, {})
    assert "CATALYST_PROVISIONING_ADAPTER must name a test fake" in problems
    assert "CATALYST_PROVISIONING_DOMAIN must be a .test domain" in problems
    assert "CATALYST_PROVISIONING_ADAPTER may not be set from the environment" in guards.provisioning_problems(
        settings, {"CATALYST_PROVISIONING_ADAPTER": "x"})
    settings.CATALYST_PROVISIONING_QUOTA_MB = 0
    assert any("never unlimited" in p for p in guards.provisioning_problems(settings, {}))
    settings.CATALYST_ENV = "staging"
    settings.CATALYST_PROVISIONING_ADAPTER = "tests.mxroute_fake.FakeMailHost"
    assert any("only in the test environment" in p for p in guards.provisioning_problems(settings, {}))
    from provisioning import adapter
    settings.CATALYST_PROVISIONING_ADAPTER = ""
    with pytest.raises(adapter.AdapterError, match="no_adapter_configured"):
        adapter.host()
    assert not hasattr(adapter.MailHost, "delete")  # no delete, suspend or domain operation exists at all



# --- PR #53 review regressions --------------------------------------------------------------------------------------

def test_review_a_429_after_the_create_landed_is_unknown_never_a_rejection(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_429")
    run_worker()
    request.refresh_from_db()
    assert request.status == "found_by_evidence"
    assert not ProvisioningAttempt.objects.filter(outcome="rejected").exists()


def test_review_a_definite_rejection_goes_to_staff_and_frees_the_address_without_a_watch(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_rejected")
    run_worker()
    request.refresh_from_db()
    assert request.status == "failed_needs_staff" and items(app, core.ITEM_FAILED).count() == 1
    services.supersede(request.pk, pv.op1, "The host rejected the request definitively")
    assert AddressReservation.objects.get(pk=request.reservation_id).released_at is not None
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"
    assert PendingAction.objects.filter(kind="provision", status="held", input_ref__startswith="returned:").count() == 1


def test_review_a_failed_absent_read_sends_nothing_and_retries(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("read_500")
    run_worker()
    outcomes = list(ProvisioningAttempt.objects.order_by("id").values_list("outcome", "code"))
    assert outcomes[0] == ("not_created", "absent_read_server_error") and outcomes[-1][0] == "succeeded"
    assert [c[0] for c in FakeMailHost.calls].count("create") == 1
    request.refresh_from_db()
    assert request.status == "verified"


@pytest.mark.parametrize("change", ["absent", "quota", "suspended"])
def test_p5_12_verification_needs_the_exact_mailbox_and_never_passes_on_anything_else(pv, monkeypatch, change):
    from provisioning import handlers
    from provisioning.adapter import Mailbox

    app, request = approved(pv, monkeypatch)
    real = handlers.CreateMailbox._result

    def tamper(self, claim, req, attempt, result):
        real(self, claim, req, attempt, result)
        key = ("example.test", "ada.example")
        if change == "absent":
            FakeMailHost.mailboxes.pop(key)
        else:
            box = FakeMailHost.mailboxes[key]
            FakeMailHost.mailboxes[key] = Mailbox(box.local_part, box.domain, 1 if change == "quota" else box.quota_mb,
                                                  box.send_limit, change == "suspended")
    monkeypatch.setattr(handlers.CreateMailbox, "_result", tamper)
    run_worker()
    request.refresh_from_db()
    assert request.status == "failed_needs_staff" and not ProvisioningEvidence.objects.filter(request=request).exists()


def test_review_a_prerequisite_broken_in_the_database_then_repaired_releases_again_on_a_fresh_address(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    bounce = StaffItem.objects.create(application=app, reason_code="hard_bounce", dedupe_key=f"inbound:{request.public_id}")
    run_worker()
    request.refresh_from_db()
    assert request.status == "failed_needs_staff" and not FakeMailHost.calls  # blocked at the boundary
    services.supersede(request.pk, pv.op1, "Delivery block found before the create")
    assert release() == {"dry_run": False, "hard_bounce_open": 1, "released": 0}
    assert items(app, core.ITEM_BLOCKED).exists()  # a release refusal leaves a staff item
    StaffItem.objects.filter(pk=bounce.pk).update(status="resolved")
    assert release()["released"] == 1  # the returned hand-off is checked against today's prerequisites
    new = request_of(app)
    assert new.pk != request.pk and new.status == "awaiting_approval"
    assert new.reservation.local_part == "ada.example"  # never tried at the host, so the same address is fine


def test_review_after_a_late_mailbox_the_stage_waits_for_the_watch_and_staff_release_the_address(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    services.confirm_found_mailbox(request_of(app).pk, pv.op1, "conflict", "Not provably the one we requested")
    services.supersede(request.pk, pv.op1, "A new address will be chosen")
    assert Application.objects.get(pk=app.pk).stage == "provisioning"  # 023 11.11: not while a watch is open
    run_worker()
    assert items(app, core.ITEM_LATE_MAILBOX).count() == 1
    assert AddressReservation.objects.get(pk=request.reservation_id).released_at is None
    with pytest.raises(services.Refused, match="reason_needed"):
        services.release_address(request.pk, pv.op1, "ok")
    services.release_address(request.pk, pv.op1, "Late mailbox recorded for revocation")
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"
    assert release()["released"] == 1
    assert request_of(app).reservation.local_part == "ada.example2"  # a tried address is never proposed again


def test_review_two_applicants_with_the_same_name_never_share_an_address(pv, monkeypatch):
    from tests.test_outbound import verified_application

    other = verified_application(email="ada.second@example.test")
    AddressReservation.objects.create(application=other, local_part="ada.example", domain="example.test",
                                      basis="naming_rule")
    app = complete(pv, monkeypatch)
    release()
    assert request_of(app).reservation.local_part == "ada.example2"


def test_review_serialization_one_open_create_per_request_in_the_database(pv, monkeypatch):
    from django.db import IntegrityError, transaction

    app, request = approved(pv, monkeypatch)
    ProvisioningAttempt.objects.create(request=request, step="create", series=0)
    with pytest.raises(IntegrityError, match="provisioning_one_open_create"), transaction.atomic():
        ProvisioningAttempt.objects.create(request=request, step="create", series=1)


def test_review_pause_is_part_of_every_effect_boundary_and_a_dry_run_writes_nothing(pv, monkeypatch):
    from workflow.models import AutomationPause

    app = complete(pv, monkeypatch)
    Application.objects.filter(pk=app.pk).update(display_name="Cher")
    out = StringIO()
    call_command("activate_provisioning", "--activation-version", "1", "--approval-ref", "D-47", "--dry-run", stdout=out)
    assert json.loads(out.getvalue())["name_needs_review"] == 1 and not StaffItem.objects.filter(application=app).exists()
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    assert core.database_problem(Application.objects.get(pk=app.pk)) == "paused"


def test_review_credential_like_notes_and_mail_host_keys_in_the_environment_are_refused(pv, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_METHOD = "checklist"
    app, request = approved(pv, monkeypatch)
    with pytest.raises(services.Refused, match="note_looks_like_a_credential"):
        services.record_checklist_creation(request.pk, pv.op1, "Created it, password: Hunter2-synthetic")
    problems = guards.provisioning_problems(settings, {"MXROUTE_API_KEY": "x", "DIRECTADMIN_LOGIN_KEY": "y"})
    assert sum("looks like a mail-host credential" in p for p in problems) == 2
    from provisioning.adapter import AdapterError
    assert AdapterError("the body had ada.example@example.test in it", sent=True).code == "adapter_error"


def test_review_the_generated_password_reaches_no_log_or_error(pv, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    password = FakeMailHost.passwords_seen[0]
    assert password not in caplog.text
    assert all(password not in str(e) for e in PendingAction.objects.values_list("last_error", flat=True))


def test_review_a_conflict_after_our_own_unknown_create_is_reconciled_and_new_series_are_bounded(pv, monkeypatch, settings):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.extend(["create_lost", "create_conflict"])
    run_worker()
    codes = list(ProvisioningAttempt.objects.filter(step="create").order_by("id").values_list("outcome", "code"))
    assert ("not_created", "conflict_after_ours") in codes  # reconciled by reading, never called foreign at once
    request.refresh_from_db()
    assert request.status == "verified"


def test_review_creates_that_keep_coming_back_not_created_stop_at_the_bound(pv, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_ATTEMPTS = 2
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.extend(["create_lost", "create_lost"])
    run_worker()
    request.refresh_from_db()
    assert request.status == "failed_needs_staff" and items(app, core.ITEM_FAILED).exists()
    assert [c[0] for c in FakeMailHost.calls].count("create") == 2



def test_review_the_p2_mail_host_setting_in_the_environment_is_still_accepted(settings):
    assert guards.provisioning_problems(settings, {"CATALYST_MAIL_HOST": "127.0.0.1", "CATALYST_MAIL_PORT": "25"}) == []


def test_review_a_changed_prerequisite_since_the_handoff_is_recorded_and_bound_into_the_new_approval(pv, monkeypatch):
    app = complete(pv, monkeypatch)
    pv.committed.connect("owner", autocommit=True).execute(  # the hand-off saw an older snapshot
        "UPDATE workflow_pendingaction SET input_ref = %s WHERE kind = 'provision'", ["agreements:" + "0" * 64])
    assert release()["released"] == 1
    assert app.events.filter(kind="provisioning_prerequisites_changed_since_handoff").exists()
    from agreements.completion import prerequisites
    assert request_of(app).prerequisite_digest == prerequisites(Application.objects.get(pk=app.pk))[1]


def test_review_without_an_adapter_nothing_is_committed_and_staff_are_told(pv, monkeypatch, settings):
    app, request = approved(pv, monkeypatch)
    settings.CATALYST_PROVISIONING_ADAPTER = ""
    run_worker()
    request.refresh_from_db()
    assert request.status == "failed_needs_staff" and not ProvisioningAttempt.objects.exists()
    assert items(app, core.ITEM_BLOCKED).count() == 1


def test_review_a_paused_application_is_refused_at_release_with_a_staff_item(pv, monkeypatch):
    from workflow.models import AutomationPause

    app = complete(pv, monkeypatch)
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    assert release() == {"dry_run": False, "paused": 1, "released": 0}
    assert items(app, core.ITEM_BLOCKED).count() == 1 and not ProvisioningRequest.objects.exists()


def test_review_supersede_waits_for_work_in_flight(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)  # the create is queued, not yet run
    with pytest.raises(services.Refused, match="work_in_flight"):
        services.supersede(request.pk, pv.op1, "Trying to retire a request mid-create")


def test_review_a_clean_watch_end_releases_the_address_and_returns_the_stage(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    services.confirm_found_mailbox(request_of(app).pk, pv.op1, "conflict", "Not provably the one we requested")
    FakeMailHost.mailboxes.clear()  # gone before the watch looks
    services.supersede(request.pk, pv.op1, "A new address will be chosen")
    with pytest.raises(services.Refused, match="watch_open"):
        services.release_address(request.pk, pv.op1, "Trying to release mid-watch")
    run_worker()
    assert app.events.filter(kind="provisioning_watch_ended").exists()
    assert AddressReservation.objects.get(pk=request.reservation_id).released_at is not None
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"
    assert PendingAction.objects.filter(kind="provision", status="held", input_ref__startswith="returned:").count() == 1
    with pytest.raises(services.Refused, match="already_released"):
        services.release_address(request.pk, pv.op1, "Released already by the watch")
