"""The destructive local alert drill must reject a remote or production daemon before writes."""

import os
import subprocess

import pytest

from tests.support import ROOT


@pytest.mark.parametrize("stack", ["staging", "production"])
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"DOCKER_CONTEXT": "production"}, "DOCKER_CONTEXT names another daemon"),
        ({"DRILL_CONTEXT": "production"}, "current Docker context is not the default"),
        ({"DOCKER_HOST": "ssh://host.test"}, "DOCKER_HOST is not the local socket"),
        (
            {"DOCKER_HOST": "unix:///tmp/forwarded.sock"},
            "DOCKER_HOST is not the local socket",
        ),
        (
            {"DRILL_ENDPOINT": "unix:///tmp/forwarded.sock"},
            "default context does not use the local socket",
        ),
        ({"DRILL_DAEMON": "other-host"}, "Docker daemon is not this host"),
        ({"DRILL_PROJECT": "live-container"}, "catalyst-production project exists"),
        ({"DRILL_VOLUMES": "live-volume"}, "catalyst-production project exists"),
        ({"DRILL_JOURNAL": "present"}, "volume catalyst-production-effects exists"),
        ({"DRILL_LIST_ERROR": "1"}, "cannot inspect containers"),
        ({"DRILL_VOLUME_ERROR": "1"}, "cannot inspect volumes"),
    ],
)
def test_alert_drill_refuses_unsafe_daemon_before_mutation(
    tmp_path, stack, overrides, reason
):
    docker = tmp_path / "docker"
    log = tmp_path / "docker.log"
    docker.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$DRILL_LOG"
case "$*" in
  'context show') echo "${DRILL_CONTEXT:-default}" ;;
  'context inspect '*) echo "${DRILL_ENDPOINT:-unix:///var/run/docker.sock}" ;;
  'info --format '*) echo "$DRILL_DAEMON" ;;
  'ps -aq '*) printf '%s' "${DRILL_PROJECT:-}"; exit "${DRILL_LIST_ERROR:-0}" ;;
  'volume ls '*) printf '%s' "${DRILL_VOLUMES:-}"; exit "${DRILL_VOLUME_ERROR:-0}" ;;
  'volume inspect catalyst-production-effects') test "${DRILL_JOURNAL:-}" = present ;;
  *) exit 91 ;;
esac
"""
    )
    docker.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "alert_drill.sh")],
        capture_output=True,
        text=True,
        timeout=15,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "CATALYST_STACK_ENV": stack,
            "DRILL_DAEMON": os.uname().nodename,
            "DRILL_LOG": str(log),
            **overrides,
        },
    )
    assert result.returncode == 2, result.stderr
    assert reason in result.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    assert not any(
        c.startswith(
            ("compose", "build", "run", "volume create", "volume rm", "image rm")
        )
        for c in calls
    )


def test_alert_drill_rejects_unknown_stack():
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "alert_drill.sh")],
        capture_output=True,
        text=True,
        timeout=15,
        env={"PATH": "/usr/bin:/bin", "CATALYST_STACK_ENV": "live"},
    )
    assert result.returncode == 2
    assert "CATALYST_STACK_ENV must be staging or production" in result.stderr
