"""9kg.40 (TEST-P6-35; 026 section 11.2): the personal-data scan over committed evidence, backup and drill receipts,
alert text and the deployment receipt, with positive controls. Every planted value is synthetic by construction: a
reserved user-assigned domain (.zz), a drama-range phone number, an invented street and the fixtures' own name."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from config import personal_data_scan as scan
from tests import support
from tests.test_acceptance import VALID

ROOT = Path(__file__).resolve().parent.parent
ADAPTERS = ROOT / "deploy" / "staging" / "adapters"
SENTINELS = {
    "email": "sentinel@catalyst-sentinel.zz",
    "phone": "+44 20 7946 0999",
    "street_address": "42 Sentinel Street",
    "fixture_name": VALID["name"],
    "token": "QmFzZTY0VG9rZW5XaXRoTWl4ZWRDYXNlMTIzNDU2Nzg5MA",
    "secret_assignment": "password=hunter2hunter2",
    "ipv4_address": "10.4.2.9",
}


def run_scan(kind, *paths, stdin=None):
    return subprocess.run([sys.executable, "-m", "config.personal_data_scan", "--class", kind, *map(str, paths)],
                          cwd=ROOT, env=support.child_env(PYTHONPATH=str(ROOT)), input=stdin, capture_output=True,
                          text=True, timeout=60)


def planted(kind, tmp_path, values):
    """One input of the class with every value planted on its own line, as that class's artifact shape."""
    if kind == "evidence":
        path = tmp_path / "028-AA-AACR-synthetic.md"
        path.write_text("# A record\n\n" + "\n".join(f"- shown live: {v}" for v in values) + "\n")
    elif kind == "backup receipt":
        path = tmp_path / "receipt.json"
        path.write_text(json.dumps({"name": "set", "manifest_sha256": "0" * 64, "notes": list(values)}, indent=1))
    elif kind == "deployment receipt":
        path = tmp_path / "20261023T103300Z.json"
        path.write_text(json.dumps({"image": "sha256:" + "a" * 64, "held_actions": dict(enumerate(values))}, indent=2))
    else:  # alert text
        path = tmp_path / "alerts.log"
        path.write_text("".join(f"high catalyst staging: {v}\n" for v in values))
    return path


@pytest.mark.parametrize("kind", ["evidence", "backup receipt", "deployment receipt", "alert text"])
def test_9kg40_a_planted_sentinel_in_each_input_class_fails_the_scan_and_the_value_is_never_printed(kind, tmp_path):
    path = planted(kind, tmp_path, SENTINELS.values())
    result = run_scan({"evidence": "evidence", "alert text": "alert"}.get(kind, "receipt"), path)
    assert result.returncode == 1, result.stderr
    found = {line.rsplit(": ", 1)[1] for line in result.stdout.splitlines()}
    assert found == set(SENTINELS), result.stdout
    for line in result.stdout.splitlines():  # the location and the pattern's name, never the value
        assert line.startswith(f"{path}:") and line.split(":")[1].isdigit(), line
    for value in SENTINELS.values():
        assert value not in result.stdout + result.stderr
    assert "hits" in result.stderr and result.stderr.count("\n") == 1
    # The positive control for the stdin form too: alert text piped in is scanned the same way.
    piped = run_scan("alert", "-", stdin=f"urgent catalyst staging: {SENTINELS['email']}\n")
    assert piped.returncode == 1 and piped.stdout == "stdin:1: email\n" and SENTINELS["email"] not in piped.stdout


def test_9kg40_the_scan_fails_closed_on_zero_files_or_an_unreadable_input(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_scan("receipt", empty).returncode == 2  # a directory with nothing to scan is not clean
    assert run_scan("receipt", tmp_path / "missing.json").returncode == 2
    (tmp_path / "blank.json").write_text("")
    assert run_scan("receipt", tmp_path / "blank.json").returncode == 2  # no line was read
    (tmp_path / "bytes.json").write_bytes(b"\xff\xfe not text")
    unreadable = run_scan("receipt", tmp_path / "bytes.json")
    assert unreadable.returncode == 2 and "unreadable" in unreadable.stderr
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps({"name": "set", "commit": "178da42"}))
    assert run_scan("receipt", clean, tmp_path / "bytes.json").returncode == 2  # one bad input fails the whole scan
    assert run_scan("evidence", "-").returncode == 2  # stdin is alert text only
    ok = run_scan("receipt", clean)
    assert (ok.returncode, ok.stdout) == (0, "") and "1 files" in ok.stderr


def test_9kg40_the_committed_evidence_passes_the_scan():
    """The repository's own records (the after-action reports, the evidence documents, the staging specification
    with its 6B records and the launch plan) carry no personal data; CI runs this with the suite."""
    result = run_scan("evidence")
    assert result.returncode == 0, result.stdout
    files = int(result.stderr.split(" files")[0].rsplit(" ", 1)[1])
    assert files >= len(scan.EVIDENCE_PATHS) and files >= 10
    for path in scan.EVIDENCE_PATHS:
        assert (ROOT / path).exists(), path


def test_9kg40_reserved_addresses_digests_run_ids_and_ranges_are_not_personal_data():
    """Negative controls: what evidence legitimately holds must not fail the scan, or the scan would be removed."""
    text = "\n".join([
        "ada@example.test onboarding@example.invalid staff@sub.example.com x@catalyst.example y@localhost.localhost",
        "run 39780920293 head 178da42 sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d",
        "2026-10-23T10:33:00Z 20261023T103300Z 13 Oct 2026 10:00:00 +0000 1052 s 28 of 28 PASS 3.14.8",
        "127.0.0.1 127.0.0.2 0.0.0.0 192.0.2.10 198.51.100.7 203.0.113.44 169.254.169.254",
        "10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 fd00::/8",
        "password: synthetic-ci-only CATALYST_SECRET_KEY=synthetic-test-only secret_key=<redacted> token=***",
        "028-AA-AACR-p6-staging 026-AT-DSGN-p6-staging-deployment-specification",
        "test_6b10_the_adapters_take_only_content_references_and_smoke_through_the_readiness_cache",
        "catalyst-v2-test-1761212345-12345-6789 registry.example/catalyst@sha256:" + "b" * 64,
    ])
    assert scan.scan_text(text) == []


def test_9kg40_email_and_token_patterns_catch_what_fixture_names_alone_would_miss():
    """Cohort data is not fixture data: an address or a token with no fixture name near it is still a hit."""
    assert scan.scan_text("reply from someone@a-cohort-member.zz\n") == [(1, "email")]
    assert scan.scan_text("Bearer " + "x" * 24 + "\n") == [(1, "bearer_token")]
    assert scan.scan_text("-----BEGIN OPENSSH PRIVATE KEY-----\n") == [(1, "private_key")]
    assert scan.scan_text("api_key = ABCDEFGHIJ\n") == [(1, "secret_assignment")]
    assert scan.scan_text("192.168.1.20 and 172.16.0.3\n") == [(1, "ipv4_address")]  # once per line per pattern
    assert scan.scan_text("(020) 7946 0999\n") == [(1, "phone")]


def test_9kg40_the_fixture_person_names_are_the_ones_the_scan_knows():
    """The fixtures' person name is on the scan's list (a receipt that carries it has a leak); a new fixture name
    goes on the list too."""
    assert VALID["name"] in scan.FIXTURE_NAMES
    assert all(" " in name and name == name.title() for name in scan.FIXTURE_NAMES)


# --- the host's receipt step -----------------------------------------------------------------------------------------

def run_receipt(tmp_path, facts, backup_receipt, label="178da42"):
    """Run the real receipt.sh (and the smoke.sh it calls) with docker stubbed: every compose exec and inspect
    answers as a healthy stack on the recorded image would, and the release facts are the given JSON."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    image_id = "sha256:" + "c" * 64
    (stubs / "docker").write_text(f"""#!/bin/sh
case "$*" in
  *"catalyst_release receipt"*) printf '%s' '{json.dumps(facts)}' ;;
  *"check --deploy"*) exit 0 ;;
  *"readyz"*) printf 'HTTP/1.0 200 OK' ;;
  *"CATALYST_WORKER_HEARTBEAT_FILE"*) printf '1' ;;
  *" ps -q "*) printf 'cid' ;;
  *"image inspect --format {{{{.Id}}}}"*) printf '{image_id}' ;;
  *"image.revision"*) printf '{label}' ;;
  *"inspect --format {{{{.Image}}}}"*) printf '{image_id} true false 0' ;;
  *) echo "unexpected docker $*" >&2; exit 9 ;;
esac
""")
    (stubs / "docker").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "current-image").write_text(image_id)
    python = os.path.dirname(sys.executable)
    env = {"PATH": f"{stubs}:{python}:/usr/bin:/bin", "CATALYST_DEPLOY_STATE": str(state),
           "CATALYST_COMPOSE_PROJECT": "p", "CATALYST_COMPOSE_FILE": "f", "CATALYST_BACKUP_RECEIPT": str(backup_receipt),
           "CATALYST_SMOKE_SETTLE": "0", "CATALYST_SMOKE_SECONDS": "2"}
    result = subprocess.run(["bash", str(ADAPTERS / "receipt.sh")], env=env, capture_output=True, text=True, timeout=60)
    receipts = sorted(p.name for p in (state / "receipts").iterdir()) if (state / "receipts").exists() else []
    return result, receipts


FACTS = {"commit": "178da42", "schema_heads": {"workflow": "0004"}, "migrations_pending": 0, "held_actions": {},
         "forward_only": []}


def test_9kg40_the_host_receipt_step_blocks_on_a_hit_and_keeps_no_receipt(tmp_path):
    backup = tmp_path / "backup-receipt.json"
    backup.write_text(json.dumps({"name": "set", "manifest_sha256": "0" * 64, "commit": "178da42"}))
    # The positive control: a value that reached the release facts would reach the receipt; the scan withholds it.
    result, receipts = run_receipt(tmp_path, {**FACTS, "held_actions": {"send_message": SENTINELS["email"]}}, backup)
    assert result.returncode == 1 and "receipt withheld" in result.stderr and "email" in result.stdout, result.stderr
    assert receipts == [] and SENTINELS["email"] not in result.stdout + result.stderr
    # The pre-deploy backup's receipt is scanned too.
    leaking = tmp_path / "leaking-backup-receipt.json"
    leaking.write_text(json.dumps({"name": "set", "operator": SENTINELS["phone"]}))
    result, receipts = run_receipt(tmp_path, FACTS, leaking)
    assert result.returncode == 1 and "receipt withheld" in result.stderr and "phone" in result.stdout
    assert receipts == []
    # A missing backup receipt is refused before any scan; an unreadable one fails the scan closed.
    result, receipts = run_receipt(tmp_path, FACTS, tmp_path / "absent.json")
    assert result.returncode == 1 and "does not exist" in result.stderr and receipts == []
    # The control: clean facts and a clean backup receipt write exactly one receipt, which reads back as written.
    result, receipts = run_receipt(tmp_path, FACTS, backup)
    assert result.returncode == 0, result.stderr
    assert len(receipts) == 1 and receipts[0].endswith(".json") and not receipts[0].startswith(".")
    written = json.loads((tmp_path / "state" / "receipts" / receipts[0]).read_text())
    assert written["commit"] == "178da42" and written["pre_deploy_backup_receipt"] == str(backup)
    assert result.stdout.strip().endswith(receipts[0])


def test_9kg40_the_receipt_step_scans_before_the_receipt_counts():
    text = (ADAPTERS / "receipt.sh").read_text()
    assert text.index("personal_data_scan --class receipt") < text.index('mv -f "$pending" "$out"')
    assert 'rm -f "$pending"' in text and "receipt withheld" in text
    assert '"$pending" "$CATALYST_BACKUP_RECEIPT"' in text  # both receipts, every time
