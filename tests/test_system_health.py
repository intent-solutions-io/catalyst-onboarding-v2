"""6B.4 (026 section 7; TEST-P6-17, 19): the worker heartbeat and the Catalyst-wide health command."""

import json
import time
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from config import system_health
from tests.mxroute_fake import FakeMailHost
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
                 "reminders", "mail"):
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
