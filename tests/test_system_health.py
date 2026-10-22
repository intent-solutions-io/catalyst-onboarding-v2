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


def test_6b4_a_quiet_system_is_healthy_and_the_report_is_counts_only(p2):
    code, report = health()
    assert code == 0 and report["anomalies"] == []
    for part in ("worker", "queue", "agreements", "provisioning", "bounces", "sends", "collector"):
        assert part in report and "anomalies" in report[part]
    assert "@" not in json.dumps(report)  # no addresses


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
    assert code == 1 and "provisioning.provisioning_needs_attention" in report["anomalies"]
    assert report["provisioning"]["requests_needing_attention"] == 1


def test_6b4_a_failing_check_exits_2_and_never_reports_a_finding(p2, monkeypatch):
    def broken():
        raise RuntimeError("database is down with secret details")
    monkeypatch.setattr(system_health, "report", broken)
    err = StringIO()
    with pytest.raises(SystemExit) as exit_:
        call_command("catalyst_health", stdout=StringIO(), stderr=err)
    assert exit_.value.code == 2 and "RuntimeError" in err.getvalue() and "secret details" not in err.getvalue()
