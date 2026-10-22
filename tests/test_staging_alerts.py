"""6B.12 (026 sections 7 and 11; TEST-P6-17 to 20, 38): the staging health check and dead-man sweep adapters. The live
cases run in scripts/alert_drill.sh on the dev box; one real delivery through the estate alert floor was verified from
Buzz (026 section 16)."""

import os
import subprocess

from tests.support import ROOT

ADAPTERS = ROOT / "deploy" / "staging" / "adapters"


def test_6b12_an_alert_carries_signal_codes_and_nothing_else():
    health = (ADAPTERS / "health.sh").read_text()
    assert '[[ "$c" =~ ^[a-z_]+\\.[a-z_]+$ ]]' in health  # every word is a code; anything else is replaced
    assert 'safe+=("health.unrecognised_signal")' in health
    assert '"catalyst staging: ${safe[*]}"' in health  # the message is the codes, never the report itself
    assert "CATALYST_NOTIFY_CMD:?" in health and "CATALYST_HEALTH_STATE:?" in health


def test_6b12_the_health_check_leaves_markers_for_the_dead_man():
    health = (ADAPTERS / "health.sh").read_text()
    assert health.index('touch "$CATALYST_HEALTH_STATE/health.started"') < health.index("manage.py catalyst_health")
    assert health.rstrip().endswith('touch "$CATALYST_HEALTH_STATE/health.ok"\nexit "$status"')


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
