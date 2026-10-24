"""6B.4 (026 section 7; TEST-P6-17, 19): the worker heartbeat and the Catalyst-wide health command."""

import json
import time
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from applications.models import Application
from config import system_health
from tests.mxroute_fake import FakeMailHost
from tests.support import resume_pauses
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, approve, approved, c, complete, d, ev, g, h, issued, k, nda, p2, pv, release, request_of, run_worker,
    sign_and_settle, tls,
)
from workflow import heartbeat
from workflow.models import PendingAction


def health() -> tuple[int, dict]:
    out = StringIO()
    try:
        call_command("catalyst_health", stdout=out)
        code = 0
    except SystemExit as exit_:
        code = exit_.code
    return code, json.loads(out.getvalue()) if out.getvalue() else {}


def test_6b4_the_heartbeat_is_written_atomically_and_never_stops_the_worker(tmp_path):
    path = str(tmp_path / "worker.beat")
    assert heartbeat.age_seconds(path) is None
    heartbeat.beat(path)
    assert heartbeat.age_seconds(path) < 5 and not (tmp_path / "worker.beat.tmp").exists()
    heartbeat.beat(str(tmp_path / "missing-dir" / "worker.beat"))  # an unwritable path raises nothing
    heartbeat.beat("")  # not configured: nothing written


def test_6b4_the_worker_beats_while_it_runs(p2, settings, tmp_path):
    settings.CATALYST_WORKER_HEARTBEAT_FILE = str(tmp_path / "worker.beat")
    call_command("run_worker", "--exit-when-idle", stdout=StringIO())
    assert heartbeat.age_seconds(settings.CATALYST_WORKER_HEARTBEAT_FILE) < 5


def test_6b4_a_quiet_system_is_healthy(p2):
    code, report = health()
    assert code == 0 and report["anomalies"] == []
    for part in ("worker", "queue", "agreements", "provisioning", "bounces", "sends", "collector", "replies",
                 "reminders", "mail", "sessions", "intake"):
        assert part in report and "anomalies" in report[part]


def test_6b4_the_report_never_carries_applicant_data(pv, monkeypatch):
    from applications.models import Application

    app = complete(pv, monkeypatch)  # a real applicant with a name, an address and agreements
    text = json.dumps(health()[1])
    for value in (app.display_name, app.email, app.email.split("@")[0], str(app.public_ref)):
        assert value and value not in text
    assert Application.objects.filter(pk=app.pk).exists()


def test_6b4_a_dead_worker_is_reported_and_recovery_clears_it(p2, settings, tmp_path):
    path = tmp_path / "worker.beat"
    settings.CATALYST_WORKER_HEARTBEAT_FILE = str(path)
    code, report = health()
    assert code == 1 and "worker.heartbeat_missing" in report["anomalies"]
    path.write_text(f"{time.time() - settings.CATALYST_HEALTH_HEARTBEAT_STALE_SECONDS - 60:.0f}\n")
    code, report = health()
    assert code == 1 and "worker.heartbeat_stale" in report["anomalies"]
    heartbeat.beat(str(path))
    code, report = health()
    assert code == 0 and report["worker"]["anomalies"] == []


def test_6b4_a_backlog_and_an_expired_lease_are_anomalies(p2, settings):
    import uuid

    old = PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                       idempotency_key="health-probe-backlog")
    PendingAction.objects.filter(pk=old.pk).update(due_at=timezone.now() - timedelta(hours=2))
    code, report = health()
    assert code == 1 and "queue.backlog" in report["anomalies"] and report["queue"]["oldest_due_seconds"] >= 7000
    PendingAction.objects.filter(pk=old.pk).update(
        status=PendingAction.Status.RUNNING, lease_token=uuid.uuid4(), lease_expires_at=timezone.now() - timedelta(hours=1))
    code, report = health()
    assert "queue.expired_leases" in report["anomalies"] and "queue.backlog" not in report["anomalies"]


def test_6b4_an_unknown_mailbox_create_is_reported_until_staff_resolve_it(pv, monkeypatch):
    app, request = approved(pv, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    code, report = health()
    assert code == 1 and "provisioning.provisioning_settling" in report["anomalies"]
    assert report["provisioning"]["requests_settling"] == 1


def test_6b4_a_conflict_alerts_until_staff_resolve_it_then_the_system_is_healthy(pv, monkeypatch):
    from provisioning import services
    from provisioning.adapter import Mailbox

    app, request = approved(pv, monkeypatch)
    FakeMailHost.mailboxes[("team.example.test", "ada.example")] = Mailbox("ada.example", "team.example.test", 50, 5, False)
    run_worker()  # someone else's mailbox: a conflict, with a staff item
    request.refresh_from_db()
    assert request.status == "conflict"
    code, report = health()
    assert "provisioning.provisioning_problem" in report["anomalies"]
    services.supersede(request.pk, pv.op1, "A new address will be chosen")  # staff handle it
    code, report = health()
    assert report["provisioning"]["anomalies"] == [], report["provisioning"]  # a handled conflict never alerts again


def backdate(env, table: str, row_id: int, column: str, seconds: int) -> None:
    """Test-only: the migration owner moves a timestamp into the past (no service ages a row on demand)."""
    owner = env.committed.connect("owner", autocommit=True)
    owner.execute(f"UPDATE {table} SET {column} = {column} - make_interval(secs => %s) WHERE id = %s", [seconds, row_id])


def test_6b4_an_aged_hard_bounce_alerts_and_a_fresh_one_does_not(pv, monkeypatch):
    from correspondence.staff_items import open_item

    app = complete(pv, monkeypatch)
    item = open_item("hard_bounce", "health-probe-bounce", application=app)
    assert health()[1]["bounces"]["anomalies"] == []  # younger than the target
    backdate(pv, "correspondence_staffitem", item.pk, "opened_at", 2 * 86400)
    code, report = health()
    assert code == 1 and "bounces.hard_bounce_unresolved" in report["anomalies"]


def test_6b4_routine_staff_waiting_alerts_only_when_overdue(pv, monkeypatch, settings):
    from correspondence.models import StaffItem

    settings.CATALYST_PROVISIONING_METHOD = "checklist"  # a checklist item opens on approval: ordinary staff work
    app, request = approved(pv, monkeypatch)
    item = StaffItem.objects.get(application=app, reason_code="provisioning_checklist", status="open")
    assert health()[1]["provisioning"]["anomalies"] == []  # a fresh checklist is not a problem
    backdate(pv, "correspondence_staffitem", item.pk, "opened_at", 2 * 3600)
    assert "provisioning.provisioning_waiting_too_long" in health()[1]["anomalies"]


def test_6b4_a_revocation_round_that_never_ran_is_reported(pv, monkeypatch):
    from provisioning import closure
    from provisioning.models import AccessRevocation

    app, request = approved(pv, monkeypatch)
    run_worker()
    closure.ensure_revocations(request, f"user:{pv.approver.pk}")  # obligations created; their round has not run
    assert AccessRevocation.objects.filter(request=request, state="requested").exists()
    assert "provisioning.revocation_stalled" not in health()[1]["anomalies"]
    # An obligation's timestamps are fixed in the database, so the health check's clock moves forward instead.
    later = timezone.now() + timedelta(hours=2)
    monkeypatch.setattr(system_health.timezone, "now", lambda: later)
    assert "provisioning.revocation_stalled" in health()[1]["anomalies"]


def test_6b4_a_lease_renewal_also_beats_the_heartbeat(p2, settings, tmp_path):
    import uuid

    from django.db import transaction

    from workflow import ledger

    settings.CATALYST_WORKER_HEARTBEAT_FILE = str(tmp_path / "worker.beat")
    action = PendingAction.objects.create(kind="health_probe", subject_type="application", subject_id=uuid.uuid4(),
                                          idempotency_key="health-probe-fence")

    class Probe:
        automated, redeliverable = True, True

    claim = ledger.claim_next({"health_probe": Probe()})
    assert claim is not None and claim.id == action.pk
    assert heartbeat.age_seconds(settings.CATALYST_WORKER_HEARTBEAT_FILE) is None
    with transaction.atomic():
        ledger.fence(claim)
    assert heartbeat.age_seconds(settings.CATALYST_WORKER_HEARTBEAT_FILE) < 5


@pytest.mark.parametrize(("column", "value", "anomaly"), [
    ("issue_status", "create_uncertain", "agreements_uncertain"),
    ("issue_status", "failed_needs_staff", "agreements_failed"),
    ("custody_status", "failed_needs_staff", "custody_failed"),
])
def test_6b4_agreement_and_custody_states_alert(k, monkeypatch, column, value, anomaly):
    from agreements.models import AgreementInstance

    app = issued(k, monkeypatch)
    assert health()[1]["agreements"]["anomalies"] == []  # an issued agreement is normal
    instance = AgreementInstance.objects.filter(application=app).first()
    owner = k.committed.connect("owner", autocommit=True)
    # test-only: the migration owner places the row in the state under test (no service reaches it on demand)
    owner.execute(f"UPDATE agreements_agreementinstance SET {column} = %s WHERE id = %s", [value, instance.pk])
    assert f"agreements.{anomaly}" in health()[1]["anomalies"]


def test_6b4_a_malformed_report_is_a_failed_check_not_a_finding(p2, monkeypatch):
    monkeypatch.setattr(system_health, "report", lambda: {"worker": {}})  # no "anomalies": the check is broken
    with pytest.raises(SystemExit) as exit_:
        call_command("catalyst_health", stdout=StringIO(), stderr=StringIO())
    assert exit_.value.code == 2


def test_6b4_a_failing_check_exits_2_and_never_reports_a_finding(p2, monkeypatch):
    def broken():
        raise RuntimeError("database is down with secret details")
    monkeypatch.setattr(system_health, "report", broken)
    err = StringIO()
    with pytest.raises(SystemExit) as exit_:
        call_command("catalyst_health", stdout=StringIO(), stderr=err)
    assert exit_.value.code == 2 and "RuntimeError" in err.getvalue() and "secret details" not in err.getvalue()


# --- 9kg.51 (029 section 5.2): the aged-waits part ------------------------------------------------------------------

def aged_codes() -> list:
    return sorted(c.split(".", 1)[1] for c in health()[1]["anomalies"] if c.startswith("aged_waits."))


def test_9kg_51_each_aged_wait_raises_its_code_and_clears_when_resolved(k, monkeypatch, settings):
    """One wait of every class, fresh (nothing raised), then past a short threshold (each code raised), then
    resolved one by one (each code clears). Codes only; the oldest age is printed per class."""
    from django.db import transaction

    from correspondence.models import InboundMessage, StaffItem
    from correspondence.staff_items import open_item
    from tests.test_assessment import scripted, valid
    from tests.test_decision import decide
    from tests.test_evidence import collect, url
    from workflow.models import AutomationPause

    classes = settings.CATALYST_HEALTH_AGED_WAIT_CLASSES
    signed = issued(k, monkeypatch)  # an NDA sent to sign, awaiting the applicant
    scripted(monkeypatch, valid())
    waiting = collect(k, email="waiting@example.test", work_url_1=url(k, "/w"), contribution="I wrote the parser.")
    held = collect(k, email="held@example.test", work_url_1=url(k, "/w"), contribution="I wrote the parser.")
    decide(k, held, "hold")
    bad = valid(quote="A quote that appears nowhere in the evidence")
    scripted(monkeypatch, bad, bad)
    stuck = collect(k, email="stuck@example.test", work_url_1=url(k, "/w"), contribution="I wrote the parser.")
    assert [a.stage for a in Application.objects.filter(pk__in=[waiting.pk, held.pk, stuck.pk]).order_by("pk")] == [
        "awaiting_decision", "on_hold", "assessing"]
    with transaction.atomic():
        item = open_item("processing_error", "aged-waits-probe", application=waiting)
    AutomationPause.objects.create(subject_type="application", subject_id=held.public_ref, reason="synthetic", actor_ref="t")
    reply = InboundMessage.objects.create(mailbox_ref="applicants", application=waiting, derived_text="A reply.",
                                          derived_text_sha256="0" * 64, classification="human", trust_decision="trusted",
                                          status="awaiting_processing", from_matches_verified_address=True)
    activation = PendingAction.objects.create(kind="provision_activate", subject_type="application", subject_id=signed.public_ref,
                                              idempotency_key="aged-waits-probe-activate")
    followon = PendingAction.objects.create(kind="send_decline", subject_type="application", subject_id=held.public_ref,
                                            idempotency_key="aged-waits-probe-decline", status="held")  # 9kg.57
    report = health()[1]["aged_waits"]  # under the default thresholds (the pending-age target): every wait is fresh
    assert aged_codes() == [] and set(report) == {*classes, "anomalies"}
    assert all(report[name]["waiting"] >= 1 and report[name]["oldest_seconds"] >= 0 for name in classes), report
    text = json.dumps(report)
    for value in (str(waiting.public_ref), str(held.public_ref), str(stuck.public_ref), str(signed.public_ref),
                  str(reply.public_id), str(item.public_id), "example.test"):
        assert value not in text
    settings.CATALYST_HEALTH_AGED_WAITS_PAGE = list(classes)  # every class pages here; the default is the three bad ones
    settings.CATALYST_HEALTH_AGED_WAIT_SECONDS = {name: 3 for name in classes}
    time.sleep(6)  # twice the threshold: a slow database never makes a wait look fresh, and the resolutions below
    # are checked well inside the next three seconds
    assert aged_codes() == sorted(classes) and health()[0] == 1
    assert health()[1]["aged_waits"]["on_hold"]["oldest_seconds"] >= 3
    # The held follow-ons have their own test (9kg.57); the decisions below create fresh ones, so stop paging that class.
    PendingAction.objects.filter(pk=followon.pk).update(status="cancelled")
    settings.CATALYST_HEALTH_AGED_WAITS_PAGE = [name for name in classes if name != "held_followons"]
    # Resolving each wait clears its code (a new wait a resolution creates is fresh, so it raises nothing yet).
    decide(k, waiting, "admit")
    assert "awaiting_decision" not in aged_codes()
    decide(k, held, "decline")
    assert "on_hold" not in aged_codes()
    decide(k, stuck, "hold", human_only_reason="Two failed runs; read every item myself.")
    assert "assessing" not in aged_codes() and "on_hold" not in aged_codes()  # the new hold is fresh
    StaffItem.objects.filter(pk=item.pk).update(status="resolved")
    # The failed runs opened assessment items for the stuck case, which a human-only decision leaves to staff.
    assert set(StaffItem.objects.filter(status="open").values_list("reason_code", flat=True)) == {"assessment_failed"}
    StaffItem.objects.filter(status="open", application=stuck).update(status="resolved")
    assert resume_pauses(held) == 1  # the pause guard (9kg.6) clears a pause only with its audited resume event
    InboundMessage.objects.filter(pk=reply.pk).update(status="processed")
    PendingAction.objects.filter(pk=activation.pk).update(status="done")
    assert aged_codes() == ["issued_agreements"]
    sign_and_settle(k, signed, "nda")  # the applicant signed and the NDA is verified; the next agreement is fresh
    assert aged_codes() == [] and health()[1]["aged_waits"]["issued_agreements"]["aged"] == 0


def test_9kg_51_thresholds_and_paging_are_per_wait_class(p2, settings):
    """The owner's values (211.7.2, 211.7.7): each class has its own threshold, and a class outside the page list is
    counted with its age but raises no anomaly."""
    from django.db import transaction

    from correspondence.staff_items import open_item
    from workflow.models import AutomationPause

    app = Application.objects.create(email="probe@example.test", email_key="probe@example.test", display_name="Synthetic")
    settings.CATALYST_HEALTH_AGED_WAIT_SECONDS = {**settings.CATALYST_HEALTH_AGED_WAIT_SECONDS, "pauses": 0.2,
                                                  "open_staff_items": 3600}
    settings.CATALYST_HEALTH_AGED_WAITS_PAGE = ["open_staff_items"]
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    with transaction.atomic():
        open_item("processing_error", "aged-waits-paging", application=app)
    time.sleep(0.5)
    report = health()[1]["aged_waits"]
    assert report["pauses"] == {"waiting": 1, "aged": 1, "oldest_seconds": 0, "threshold_seconds": 0, "pages": False}
    assert report["open_staff_items"]["aged"] == 0 and report["open_staff_items"]["pages"] is True
    assert report["anomalies"] == []  # an aged pause is counted and printed, but does not page
    settings.CATALYST_HEALTH_AGED_WAITS_PAGE = list(settings.CATALYST_HEALTH_AGED_WAIT_CLASSES)
    assert aged_codes() == ["pauses"]


def test_9kg_51_the_default_page_list_is_the_three_bad_classes_and_the_authority_flag_is_reported(p2):
    from config.settings import CATALYST_HEALTH_AGED_WAITS_PAGE  # the module default, not the test's override

    assert CATALYST_HEALTH_AGED_WAITS_PAGE == ["replies_awaiting_processing", "issued_agreements", "provisioning_activation"]
    report = health()[1]
    assert report["decision"] == {"qualification_authority_configured": False, "anomalies": []}


def test_9kg_57_held_followons_age_each_held_kind_from_its_last_hold_and_raise_their_own_code(pv, monkeypatch, settings):
    """Held `issue_nda` (an admit), `send_decline` (a decline's notice, held until oc4.11), and the `provision` hand-off
    an application in `agreements_complete` waits on, each aged past the class's own threshold, raise
    `aged_waits.held_followons`; a released or cancelled follow-on and a held action of another kind are not counted.
    Codes, kind names and counts only."""
    from tests.test_assessment import scripted, valid
    from tests.test_decision import decide
    from tests.test_evidence import collect, url

    done = complete(pv, monkeypatch)  # agreements complete: the held `provision` hand-off awaits the owner's release
    scripted(monkeypatch, valid())
    nda = collect(pv, email="nda@example.test", work_url_1=url(pv, "/w"), contribution="I wrote the parser.")
    decide(pv, nda, "admit")  # the admit's `issue_nda` is created held (activation already ran for the first case)
    assert PendingAction.objects.filter(kind="issue_nda", subject_id=nda.public_ref, status="held").exists()
    PendingAction.objects.create(kind="send_decline", subject_type="application", subject_id=nda.public_ref,
                                 idempotency_key="held-followons-decline", status="held")  # by kind and status, oc4.11 or not
    PendingAction.objects.create(kind="start_evidence_collection", subject_type="application", subject_id=nda.public_ref,
                                 idempotency_key="held-followons-other-kind", status="held")  # not a follow-on: not counted
    settings.CATALYST_HEALTH_AGED_WAIT_SECONDS = {**settings.CATALYST_HEALTH_AGED_WAIT_SECONDS, "held_followons": 3}
    report = health()[1]["aged_waits"]["held_followons"]
    assert (report["waiting"], report["aged"], report["threshold_seconds"], report["pages"]) == (3, 0, 3, False)
    assert aged_codes() == []  # fresh, and audit only by default (the default page list leaves the class out)
    settings.CATALYST_HEALTH_AGED_WAITS_PAGE = ["held_followons"]
    assert aged_codes() == []  # still fresh
    time.sleep(4)
    report = health()[1]["aged_waits"]["held_followons"]
    assert report["aged_by_kind"] == {"send_decline": 1, "issue_nda": 1, "provision": 1} and report["oldest_seconds"] >= 3
    assert aged_codes() == ["held_followons"] and health()[0] == 1
    text = json.dumps(health()[1])
    assert str(done.public_ref) not in text and str(nda.public_ref) not in text
    # Each follow-on leaving held clears its share; the code clears with the last one.
    for kind, status in (("issue_nda", "queued"), ("send_decline", "cancelled")):  # released by the owner; withdrawn
        PendingAction.objects.filter(kind=kind, status="held").update(status=status)
        assert aged_codes() == ["held_followons"]
    assert Application.objects.get(pk=done.pk).stage == "agreements_complete"
    PendingAction.objects.filter(kind="provision", status="held").update(status="queued")  # the owner's release
    assert aged_codes() == [] and health()[1]["aged_waits"]["held_followons"]["waiting"] == 0
    # A follow-on returned to held ages from its return, not from its creation (the refused `issue_nda` case).
    PendingAction.objects.filter(kind="issue_nda").update(status="held", updated_at=timezone.now())
    assert health()[1]["aged_waits"]["held_followons"]["aged"] == 0 and aged_codes() == []
