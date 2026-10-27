"""6B.12 (026 sections 7 and 11; TEST-P6-17 to 20, 38): the staging health check and dead-man sweep adapters. The live
cases run in scripts/alert_drill.sh on the dev box; one real delivery through the estate alert floor was verified from
Buzz (026 section 16)."""

import os
import subprocess
import sys

from tests.support import ROOT

ADAPTERS = ROOT / "deploy" / "staging" / "adapters"


def test_6b12_an_alert_carries_signal_codes_and_nothing_else():
    health = (ADAPTERS / "health.sh").read_text()
    assert '[[ "$c" =~ ^[a-z_]+\\.[a-z_]+$ ]]' in health  # every word is a code; anything else is replaced
    assert 'safe+=("health.unrecognised_signal")' in health
    # The message is the codes, never the report itself; the stack name comes from a fixed list (stack.sh, 9kg.78.1).
    assert '"catalyst ${STACK}: ${safe[*]}"' in health
    assert "staging) PROBE_TLS" in (ADAPTERS / "stack.sh").read_text() and "*) echo" in (ADAPTERS / "stack.sh").read_text()
    assert "CATALYST_NOTIFY_CMD:?" in health and "CATALYST_HEALTH_STATE:?" in health


def run_health(tmp_path, health_rc, health_out="", worker_running=True, notify_ok=True, form="200", extra=None):
    """Run the real health.sh with docker and curl stubbed: `docker ... exec` prints health_out and exits health_rc."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    (stubs / "docker").write_text(f"""#!/bin/sh
case "$*" in
  *" ps -q worker"*) {"echo worker-id" if worker_running else "true"} ;;
  inspect*) echo {"true" if worker_running else "false"} ;;
  exec*) printf '%s' '{health_out}'; exit {health_rc} ;;
esac
""")
    (stubs / "curl").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{tmp_path}/curl.args'\nprintf '%s' '{form}'\n")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    state, log = tmp_path / "health", tmp_path / "alerts.log"
    notify = f"printf '%s %s\\n' >> {log}" if notify_ok else "false"
    python = os.path.dirname(sys.executable)  # the host's python3 parses the report; the test image keeps it here
    env = {"PATH": f"{stubs}:{python}:/usr/bin:/bin", "CATALYST_HEALTH_STATE": str(state), "CATALYST_NOTIFY_CMD": notify,
           "CATALYST_DEPLOY_STATE": str(tmp_path), "CATALYST_COMPOSE_PROJECT": "p", "CATALYST_COMPOSE_FILE": "f",
           "CATALYST_SMOKE_URL": "https://catalyst.example.test/request-access/", **(extra or {})}
    result = subprocess.run(["bash", str(ADAPTERS / "health.sh")], env=env, capture_output=True, text=True, timeout=30)
    alerts = log.read_text() if log.exists() else ""
    if log.exists():
        log.unlink()
    return result.returncode, alerts, (state / "health.ok").exists()


def test_6b12_a_healthy_report_sends_nothing_and_leaves_the_marker(tmp_path):
    assert run_health(tmp_path, 0, '{"anomalies": []}') == (0, "", True)


def test_6b12_a_check_that_fails_without_a_report_is_never_healthy(tmp_path):
    """Exit 1 with no JSON (a settings or import error) was silently healthy before the 6B.12 review."""
    assert run_health(tmp_path, 1, "") == (1, "urgent catalyst staging: health.check_failed\n", True)
    assert run_health(tmp_path, 2, "") == (1, "urgent catalyst staging: health.check_failed\n", True)


def test_6b12_findings_are_codes_and_a_stale_heartbeat_is_urgent(tmp_path):
    report = '{"anomalies": ["queue.backlog", "worker.heartbeat_stale", "x.Evil <b>", "bounces.hard_bounce_unresolved"]}'
    rc, alerts, _ = run_health(tmp_path, 1, report)
    assert rc == 1 and alerts == ("urgent catalyst staging: bounces.hard_bounce_unresolved health.unrecognised_signal "
                                  "queue.backlog worker.heartbeat_stale\n")


def test_6b12_a_stopped_worker_and_an_unreachable_form_are_reported(tmp_path):
    rc, alerts, _ = run_health(tmp_path, 0, '{"anomalies": []}', worker_running=False, form="000")
    assert rc == 1 and alerts == "urgent catalyst staging: health.worker_unreachable probe.public_form_unreachable\n"


def test_6b12_recovery_is_noted_once_and_retried_if_the_note_failed(tmp_path):
    run_health(tmp_path, 1, '{"anomalies": ["queue.backlog"]}')
    assert run_health(tmp_path, 0, '{"anomalies": []}', notify_ok=False)[0] == 3  # the recovery note failed
    assert run_health(tmp_path, 0, '{"anomalies": []}') == (0, "info catalyst staging: recovered\n", True)  # retried
    assert run_health(tmp_path, 0, '{"anomalies": []}') == (0, "", True)  # and only once


def run_sweep(tmp_path, age_minutes, stale="900"):
    marker = tmp_path / "health.ok"
    if age_minutes is not None:
        marker.touch()
        old = marker.stat().st_mtime - age_minutes * 60
        os.utime(marker, (old, old))
    log = tmp_path / "alerts.log"
    env = {"PATH": "/usr/bin:/bin", "CATALYST_HEALTH_STATE": str(tmp_path), "CATALYST_HEALTH_STALE_SECONDS": stale,
           "CATALYST_NOTIFY_CMD": f"printf '%s %s\\n' >> {log}"}
    result = subprocess.run(["bash", str(ADAPTERS / "sweep.sh")], env=env, capture_output=True, text=True, timeout=30)
    return result.returncode, log.read_text() if log.exists() else ""


def test_6b12_the_sweep_is_quiet_while_the_health_check_is_fresh(tmp_path):
    assert run_sweep(tmp_path, 1) == (0, "")


def test_6b12_the_sweep_alerts_when_the_health_check_is_stale_or_never_ran(tmp_path):
    assert run_sweep(tmp_path, 20) == (1, "urgent catalyst staging: health.check_stale\n")
    (tmp_path / "alerts.log").unlink()
    (tmp_path / "health.ok").unlink()
    assert run_sweep(tmp_path, None) == (1, "urgent catalyst staging: health.check_stale\n")


def aged(path, hours, text=""):
    path.write_text(text)
    old = path.stat().st_mtime - hours * 3600
    os.utime(path, (old, old))


def test_6b13_a_stale_backup_and_an_overdue_restore_drill_are_reported(tmp_path):
    backups, drills = tmp_path / "backups", tmp_path / "drills"
    backups.mkdir()
    drills.mkdir()
    extra = {"CATALYST_BACKUP_RECEIPTS": str(backups), "CATALYST_DRILL_RECEIPTS": str(drills)}
    aged(backups / "receipt.json", 26.1)
    aged(drills / "drill.json", 24 * 34, '{"result": "pass"}')
    rc, alerts, _ = run_health(tmp_path, 0, '{"anomalies": []}', extra=extra)
    assert rc == 1 and alerts == "high catalyst staging: backup.stale\n"  # 26 h 6 min old; the drill 34 days
    aged(backups / "receipt.json", 25.9)
    aged(drills / "drill.json", 24 * 36, '{"result": "pass"}')
    rc, alerts, _ = run_health(tmp_path, 0, '{"anomalies": []}', extra=extra)
    assert rc == 1 and alerts == "high catalyst staging: restore_drill.overdue\n"  # the drill 36 days


def test_6b13_a_failed_drill_never_counts_as_a_drill_done(tmp_path):
    drills = tmp_path / "drills"
    drills.mkdir()
    aged(drills / "old-pass.json", 24 * 36, '{"result": "pass"}')
    aged(drills / "new-fail.json", 1, '{"result": "fail"}')  # newest, but failed
    rc, alerts, _ = run_health(tmp_path, 0, '{"anomalies": []}', extra={"CATALYST_DRILL_RECEIPTS": str(drills)})
    assert rc == 1 and alerts == "high catalyst staging: restore_drill.overdue\n"
    aged(drills / "newer-pass.json", 0, '{"result": "pass"}')
    assert run_health(tmp_path, 0, '{"anomalies": []}', extra={"CATALYST_DRILL_RECEIPTS": str(drills)})[0] == 0


def test_6b13_a_missing_or_empty_receipt_directory_counts_as_stale(tmp_path):
    extra = {"CATALYST_BACKUP_RECEIPTS": str(tmp_path / "missing"), "CATALYST_DRILL_RECEIPTS": str(tmp_path)}
    rc, alerts, _ = run_health(tmp_path, 0, '{"anomalies": []}', extra=extra)
    assert rc == 1 and alerts == "high catalyst staging: backup.stale restore_drill.overdue\n"


# --- 9kg.78.1: the adapters name their stack and verify TLS outside staging -----------------------------------------

def curl_args(tmp_path) -> str:
    path = tmp_path / "curl.args"
    text = path.read_text() if path.exists() else ""
    if path.exists():
        path.unlink()
    return text


def test_9kg_78_1_alerts_name_the_stack_and_staging_stays_the_default(tmp_path):
    stale = '{"anomalies": ["worker.heartbeat_stale"]}'
    rc, alerts, _ = run_health(tmp_path, 1, stale)
    assert rc == 1 and alerts.startswith("urgent catalyst staging: ")
    rc, alerts, _ = run_health(tmp_path, 1, stale, extra={"CATALYST_STACK_ENV": "production"})
    assert rc == 1 and alerts == "urgent catalyst production: worker.heartbeat_stale\n"
    (tmp_path / "health" / "health.ok").unlink()
    rc, alerts, ok = run_health(tmp_path, 1, stale, extra={"CATALYST_STACK_ENV": "prod"})
    assert rc == 2 and alerts == "" and not ok  # an unknown stack is refused before anything runs


def test_9kg_78_1_the_probe_verifies_tls_outside_staging(tmp_path):
    run_health(tmp_path, 0, "{}")
    assert " -k " in f" {curl_args(tmp_path)} "  # staging's internal CA
    run_health(tmp_path, 0, "{}", extra={"CATALYST_STACK_ENV": "production"})
    args = f" {curl_args(tmp_path)} "
    assert " -k " not in args and "--insecure" not in args and "--cacert" not in args
    run_health(tmp_path, 0, "{}", extra={"CATALYST_STACK_ENV": "production", "CATALYST_PROBE_CA_FILE": "/etc/catalyst/proxy-ca.pem"})
    args = f" {curl_args(tmp_path)} "
    assert " -k " not in args and "--cacert /etc/catalyst/proxy-ca.pem" in args
    for script in ("health.sh", "smoke.sh"):
        assert "curl -sk" not in (ADAPTERS / script).read_text(), script  # TLS arguments come from stack.sh only


def test_9kg_78_1_the_sweep_names_the_stack(tmp_path):
    log = tmp_path / "alerts.log"
    env = {"PATH": "/usr/bin:/bin", "CATALYST_HEALTH_STATE": str(tmp_path), "CATALYST_HEALTH_STALE_SECONDS": "60",
           "CATALYST_NOTIFY_CMD": f"printf '%s %s\\n' >> {log}", "CATALYST_STACK_ENV": "production"}
    result = subprocess.run(["bash", str(ADAPTERS / "sweep.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and log.read_text() == "urgent catalyst production: health.check_stale\n"
    env["CATALYST_STACK_ENV"] = "live"
    log.unlink()
    result = subprocess.run(["bash", str(ADAPTERS / "sweep.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and not log.exists()
