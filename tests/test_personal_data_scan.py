"""9kg.40 (TEST-P6-35; 026 section 11.2): the personal-data scan over committed evidence, backup and drill receipts,
alert text and the deployment receipt, with positive controls. Every planted value is synthetic by construction: a
reserved user-assigned domain (.zz), a drama-range phone number, an invented street and the fixtures' own name."""

import base64
import json
import os
import re
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
    # Built at import so no high-entropy literal sits in the source: a squash merge re-commits a literal under a
    # new commit, which the history secret scan reports again (PR #88; .gitleaksignore).
    "token": base64.b64encode(b"Base64TokenWithMixedCase1234567890").decode().rstrip("="),
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


def test_9kg40_an_undecodable_stdin_is_reported_with_a_fixed_message_never_its_bytes():
    result = subprocess.run([sys.executable, "-m", "config.personal_data_scan", "--class", "alert", "-"], cwd=ROOT,
                            env=support.child_env(PYTHONPATH=str(ROOT)), input=b"urgent \xff\xfe\x80 text", capture_output=True,
                            timeout=60)
    assert result.returncode == 2 and b"stdin is not UTF-8 text" in result.stderr
    assert b"\xff" not in result.stderr + result.stdout and b"0xff" not in result.stderr.lower()


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
    for pattern in scan.EVIDENCE_PATHS:
        assert list(ROOT.glob(pattern)), pattern  # every class in the set matches something (an empty glob fails closed)


def test_9kg40_reserved_addresses_digests_run_ids_paths_and_ranges_are_not_personal_data():
    """Negative controls: what evidence legitimately holds must not fail the scan, or the scan would be removed."""
    text = "\n".join([
        "ada@example.test onboarding@example.invalid staff@sub.example.com x@catalyst.example y@localhost.localhost",
        "/var/backups/catalyst/20261023T030000Z/receipt /var/lib/catalyst/backups/catalyst-20261023T103300Z/receipt.json",
        "/srv/catalyst/Deploy7State/receipts/20261023T103300Z.json and operations/drill-first/pre-deploy-backup.json",
        "lease_token = models.UUIDField(null=True) and filter(lease_token=tok).update(status='done')",
        "A synthetic applicant asks for access; a wrong adoption hands someone else's mailbox to an applicant.",
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
    assert scan.scan_text("x@myexample.com\n") == [(1, "email")]  # reserved domains match as a domain, never a suffix
    assert scan.scan_text("Bearer " + "x" * 24 + "\n") == [(1, "bearer_token")]
    assert scan.scan_text("-----BEGIN OPENSSH PRIVATE KEY-----\n") == [(1, "private_key")]
    assert scan.scan_text("api_key = ABCDEFGHIJ\n") == [(1, "secret_assignment")]
    assert scan.scan_text('"password": "hunter2hunter2"\n') == [(1, "secret_assignment")]  # a quoted key
    assert scan.scan_text("DB_PASSWORD=hunter2hunter2\n") == [(1, "secret_assignment")]  # a wider identifier
    assert scan.scan_text("CATALYST_SECRET_KEY=hunter2hunter2\n") == [(1, "secret_assignment")]  # the control's twin
    assert scan.scan_text("CATALYST_SECRET_KEY=synthetic-test-only\n") == []  # passes for the synthetic value only
    assert scan.scan_text("192.168.1.20 and 172.16.0.3\n") == [(1, "ipv4_address")]  # once per line per pattern
    assert scan.scan_text("(020) 7946 0999\n") == [(1, "phone")]
    assert scan.scan_text("(555)123-4567\n") == [(1, "phone")]  # a bracketed area code with no separator after it
    assert scan.scan_text("5551234567\n") == []  # the stated floor: an unseparated number is not detected
    token = "Zz9" * 14
    assert scan.scan_text(f"/var/lib/{token}/receipt.json\n") == [(1, "token")]  # a token inside a path is still one


def test_9kg40_a_value_split_across_a_wrapped_line_is_found_at_the_paragraphs_first_line():
    text = "An applicant named Ada\nExample wrote from +44 20\n7946 0999 on Tuesday.\n\nA clean paragraph.\n"
    assert scan.scan_text(text) == [(1, "fixture_name"), (1, "phone")]
    assert scan.scan_text("x@myexample.com\nAda Example\n") == [(1, "email"), (2, "fixture_name")]  # not reported twice


def test_9kg40_every_fixture_person_name_is_on_the_scans_list_and_matched_whatever_its_case():
    """Every name the fixtures give an applicant is a hit, in any case; the generic labels only in their exact case,
    so the same words as prose ("a synthetic applicant", "someone else's") are not a name. A real person's name is on
    no list: the scan does not detect real names."""
    used = set()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        used |= set(re.findall(r'(?:\bname=|"name": )"([A-Z][a-z]+ [A-Z][a-z]+)"', path.read_text()))
    assert used and used <= set(scan.FIXTURE_NAMES) | set(scan.FIXTURE_LABELS), used - set(scan.FIXTURE_NAMES) - set(scan.FIXTURE_LABELS)
    assert VALID["name"] in scan.FIXTURE_NAMES and {"Calm Example", "Other Example", "Queued Example", "Ada Two"} <= set(scan.FIXTURE_NAMES)
    for name in scan.FIXTURE_NAMES:
        for form in (name, name.lower(), name.upper()):
            assert scan.scan_text(f"applicant {form} wrote\n") == [(1, "fixture_name")], form
    for label in scan.FIXTURE_LABELS:
        assert scan.scan_text(f"{label}\n") == [(1, "fixture_name")]
        assert scan.scan_text(f"a {label.lower()}'s\n") == []
    assert scan.scan_text("Adam Example-Smith\n") == []  # a longer name is not the fixture's


def test_9kg40_every_filed_document_of_an_evidence_class_is_in_the_scanned_set():
    """A new after-action report, analysis or test evidence or decision record is scanned without a code change."""
    scanned = {p.relative_to(ROOT).as_posix() for p in scan.files("evidence", [])}
    docs = ROOT / "000-docs"
    expected = {p.relative_to(ROOT).as_posix() for p in docs.glob("000-aars/*.md")}
    for code in ("RA-ANLY", "TQ-TEST", "AT-DECR"):
        expected |= {p.relative_to(ROOT).as_posix() for p in docs.glob(f"*-{code}-*.md")}
    expected |= {"000-docs/026-AT-DSGN-p6-staging-deployment-specification.md",
                 "000-docs/029-PP-PLAN-internal-launch-comparison-and-execution-plan.md"}
    assert scanned == expected and len(scanned) >= 11
    assert any(name.startswith("000-docs/030-AT-DECR") for name in scanned)  # the council record, filed after the scan


# --- the host's receipt step -----------------------------------------------------------------------------------------

COMMIT = "178da42" + "0" * 33  # a full sha, as the deploy operation requires


def run_receipt(tmp_path, facts, backup_receipt_text, label=COMMIT, remove_backup_receipt=False):
    """Run the real receipt.sh (and the smoke.sh it calls) with docker stubbed: every compose exec and inspect
    answers as a healthy stack on the recorded image would, the release facts are the given JSON, and a real deploy
    operation (config.release; 9kg.37) is started with the pre-deploy backup's receipt bound to it."""
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
    run_receipt.calls = getattr(run_receipt, "calls", 0) + 1
    state = tmp_path / f"state{run_receipt.calls}"
    state.mkdir()
    (state / "current-image").write_text(image_id)
    env = support.child_env(PYTHONPATH=str(ROOT))
    operation = lambda *args: subprocess.run([sys.executable, "-m", "config.release", "operation", *args], cwd=ROOT, env=env,
                                             capture_output=True, text=True, timeout=30)
    assert operation("start", str(state), "deploy-1", image_id, label, "-").returncode == 0
    backup = state / "backup-receipt.json"  # written after the operation started, so it is not stale
    backup.write_text(backup_receipt_text)
    bound = operation("bind", str(state), "deploy-1", str(backup))
    assert bound.returncode == 0 and bound.stdout.strip(), bound.stderr
    if remove_backup_receipt:
        backup.unlink()
    python = os.path.dirname(sys.executable)
    env = {"PATH": f"{stubs}:{python}:/usr/bin:/bin", "CATALYST_DEPLOY_STATE": str(state), "CATALYST_DEPLOY_ID": "deploy-1",
           "CATALYST_COMPOSE_PROJECT": "p", "CATALYST_COMPOSE_FILE": "f", "CATALYST_SMOKE_SETTLE": "0",
           "CATALYST_SMOKE_SECONDS": "2"}
    result = subprocess.run(["bash", str(ADAPTERS / "receipt.sh")], env=env, capture_output=True, text=True, timeout=60)
    receipts = sorted(p.name for p in (state / "receipts").iterdir()) if (state / "receipts").exists() else []
    return result, receipts, state, backup


FACTS = {"commit": COMMIT, "schema_heads": {"workflow": "0005"}, "migrations_pending": 0, "held_actions": {},
         "forward_only": [], "intake_mode": "invitation"}
CLEAN_BACKUP = json.dumps({"name": "set", "manifest_sha256": "0" * 64, "commit": COMMIT})


def test_9kg40_the_host_receipt_step_blocks_on_a_hit_and_keeps_no_receipt(tmp_path):
    # The positive control: a value that reached the release facts would reach the receipt; the scan withholds it.
    result, receipts, _, _ = run_receipt(tmp_path, {**FACTS, "held_actions": {"send_message": SENTINELS["email"]}}, CLEAN_BACKUP)
    assert result.returncode == 1 and "receipt withheld" in result.stderr and "email" in result.stdout, result.stderr
    assert receipts == [] and SENTINELS["email"] not in result.stdout + result.stderr
    # The bound pre-deploy backup's receipt is scanned too.
    result, receipts, _, _ = run_receipt(tmp_path, FACTS, json.dumps({"name": "set", "operator": SENTINELS["phone"]}))
    assert result.returncode == 1 and "receipt withheld" in result.stderr and "phone" in result.stdout
    assert receipts == [] and SENTINELS["phone"] not in result.stdout + result.stderr
    # A bound backup receipt that is gone fails the scan closed: withheld, never a clean receipt.
    result, receipts, _, _ = run_receipt(tmp_path, FACTS, CLEAN_BACKUP, remove_backup_receipt=True)
    assert result.returncode == 1 and "receipt withheld" in result.stderr and "unreadable" in result.stderr and receipts == []
    # The control: clean facts and a clean backup receipt write exactly one receipt, which reads back as written.
    result, receipts, state, backup = run_receipt(tmp_path, FACTS, CLEAN_BACKUP)
    assert result.returncode == 0, result.stderr
    assert len(receipts) == 1 and receipts[0].endswith(".json") and not receipts[0].startswith(".")
    assert oct((state / "receipts" / receipts[0]).stat().st_mode & 0o777) == "0o640"  # set before the move
    written = json.loads((state / "receipts" / receipts[0]).read_text())
    assert written["commit"] == COMMIT and written["operation"] == "deploy"
    assert written["pre_deploy_backup"]["receipt"] == str(backup.resolve())
    assert result.stdout.strip().endswith(receipts[0])


def test_9kg40_the_receipt_step_scans_before_the_receipt_counts():
    text = (ADAPTERS / "receipt.sh").read_text()
    assert text.index("personal_data_scan --class receipt") < text.index('mv -f "$pending" "$out"') < text.index("receipt mismatch")
    assert 'rm -f "$pending"' in text and "receipt withheld" in text
    assert text.index('trap \'rm -f "$pending"\' EXIT') == text.index("mktemp") + text[text.index("mktemp"):].index("\n") + 1  # right after mktemp
    assert text.index('chmod 0640 "$pending"') < text.index('mv -f "$pending" "$out"')
    assert '"$pending" ${bound:+"$bound"}' in text  # the deployment receipt and the bound backup receipt, every time
