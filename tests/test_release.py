"""6B.10 (026 sections 4 and 9; TEST-P6-17 to 20): release bookkeeping, the deploy adapters' rules, and the image
workflow. The adapters themselves are driven by the estate deploy wrapper in scripts/deploy_drill.sh on the dev box
(a good release promoted, a broken one reverted, a forward-only revert refused)."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from io import StringIO

import pytest
from django.core.management import call_command

from config import health, release
from tests.support import ROOT
from tests.test_outbound import p2  # noqa: F401  (fixture chain)

ADAPTERS = ROOT / "deploy" / "staging" / "adapters"


def test_6b10_an_image_lists_its_migrations_with_no_settings_and_no_database():
    result = subprocess.run([sys.executable, "-m", "config.release", "known"], cwd=ROOT, capture_output=True,
                            text=True, env={"PATH": "/usr/bin:/bin"}, timeout=30)
    assert result.returncode == 0, result.stderr
    known = json.loads(result.stdout)
    assert known == release.known() and "workflow.0004_restore_hold_protection" in known
    assert all(re.fullmatch(r"[a-z_]+\.\d{4}_\w+", name) for name in known)


def test_6b10_forward_only_migrations_block_only_an_image_that_does_not_know_them():
    applied = ["workflow.0001_initial", "workflow.0002_role_grants", "workflow.0003_backup_role_reads"]
    older = applied[:2]
    assert release.blockers(applied, older, {"workflow.0003_backup_role_reads"}) == ["workflow.0003_backup_role_reads"]
    assert release.blockers(applied, older, set()) == []  # expand and contract: an older image runs on the newer schema
    assert release.blockers(applied, applied, {"workflow.0003_backup_role_reads"}) == []
    assert release.blockers(older, older, {"workflow.0003_backup_role_reads"}) == []  # not applied: nothing to undo
    assert release.FORWARD_ONLY <= set(release.known())  # a listed migration must exist


def test_6b10_every_contracting_migration_is_marked_forward_only_or_reviewed_as_safe():
    """PR #73 review: the forward-only guard is not left to memory. A new migration that removes, renames or alters a
    field or model, or constrains an existing table, fails here until its release lists it in FORWARD_ONLY or records
    in EXPAND_SAFE why the previous image still runs."""
    flagged = release.contracting()
    unreviewed = sorted(set(flagged) - release.FORWARD_ONLY - set(release.EXPAND_SAFE))
    assert unreviewed == [], f"mark these FORWARD_ONLY or EXPAND_SAFE (with the reason): {unreviewed}"
    assert set(release.EXPAND_SAFE) <= set(flagged), "an EXPAND_SAFE entry no longer needs to be there"
    assert all(len(reason) > 20 for reason in release.EXPAND_SAFE.values())
    # The baseline is exactly what existed when the guard arrived: a later migration must never hide inside it.
    last = {}
    for name in release.known():
        app, migration = name.split(".", 1)
        last[app] = max(last.get(app, ""), migration)
    assert all(release.BASELINE[app] <= last[app] for app in release.APPS)
    assert release.contracting(baseline={})["correspondence.0013_clarification_and_interpretation"] == ["AddConstraint", "AddField"]


def test_6b10_the_contracting_scan_sees_a_removed_field_and_ignores_a_new_table(tmp_path):
    for app in release.APPS:
        (tmp_path / app / "migrations").mkdir(parents=True)
    (tmp_path / "workflow" / "migrations" / "0099_drop.py").write_text(
        "from django.db import migrations\n\nclass Migration(migrations.Migration):\n"
        "    operations = [migrations.RemoveField(model_name='pendingaction', name='input_ref')]\n")
    (tmp_path / "workflow" / "migrations" / "0098_new.py").write_text(
        "from django.db import migrations, models\n\nclass Migration(migrations.Migration):\n"
        "    operations = [migrations.CreateModel(name='Fresh', fields=[]),\n"
        "                  migrations.AddConstraint(model_name='fresh', constraint=models.CheckConstraint(\n"
        "                      condition=models.Q(id__gt=0), name='fresh_positive'))]\n")
    (tmp_path / "workflow" / "migrations" / "0097_column.py").write_text(
        "from django.db import migrations, models\n\nclass Migration(migrations.Migration):\n"
        "    operations = [migrations.AddField(model_name='pendingaction', name='a', field=models.IntegerField(default=0)),\n"
        "                  migrations.AddField(model_name='pendingaction', name='b', field=models.IntegerField(null=True)),\n"
        "                  migrations.AddField(model_name='pendingaction', name='c', field=models.IntegerField(db_default=0))]\n")
    assert release.contracting(tmp_path, baseline={}) == {"workflow.0097_column": ["AddField"],  # only `a` counts
                                                          "workflow.0099_drop": ["RemoveField"]}


def test_6b10_the_release_apps_are_every_first_party_app():
    from django.apps import apps

    first_party = {c.name for c in apps.get_app_configs() if (ROOT / c.name.split(".")[0]).is_dir()
                   and (ROOT / c.name / "migrations").is_dir()}
    assert first_party == set(release.APPS)  # a new app is never invisible to known() and applied


def test_6b10_the_blockers_command_is_the_tested_function():
    args = [json.dumps(["workflow.0003_backup_role_reads"]), json.dumps([]), json.dumps(["workflow.0003_backup_role_reads"])]
    result = subprocess.run([sys.executable, "-m", "config.release", "blockers", *args], cwd=ROOT, capture_output=True,
                            text=True, env={"PATH": "/usr/bin:/bin"}, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "workflow.0003_backup_role_reads"


def test_6b10_release_facts_read_back_from_the_database(p2):
    out = StringIO()
    call_command("catalyst_release", "applied", stdout=out)
    applied = json.loads(out.getvalue())
    assert set(applied) == set(release.known())  # the test database is at head
    out = StringIO()
    call_command("catalyst_release", "receipt", stdout=out)
    receipt = json.loads(out.getvalue())
    assert receipt["migrations_pending"] == 0 and receipt["schema_heads"]["workflow"] == "0006_restore_hold_insert_guard"
    assert set(receipt) == {"commit", "schema_heads", "migrations_pending", "held_actions", "forward_only", "intake_mode"}
    assert receipt["intake_mode"] in ("invitation", "open")  # 9kg.43: the receipt names the mode (opened per test)
    assert "@" not in out.getvalue()  # counts and names only


def test_6b10_the_adapters_take_only_content_references_and_smoke_through_the_readiness_cache():
    lib = (ADAPTERS / "lib.sh").read_text()
    pattern = re.search(r"IMAGE_REF='([^']+)'", lib).group(1)
    for good in ("sha256:" + "a" * 64, "registry.example/catalyst@sha256:" + "b" * 64):
        assert re.fullmatch(pattern.strip("^$"), good)
    for bad in ("catalyst:latest", "catalyst", "sha256:abc", "catalyst:1.0@sha256:short"):
        assert not re.fullmatch(pattern.strip("^$"), bad)
    smoke = (ADAPTERS / "smoke.sh").read_text()
    seconds = int(re.search(r"CATALYST_SMOKE_SECONDS:-(\d+)", smoke).group(1))
    assert seconds >= 2 * health.CACHE_SECONDS  # a readiness answer may be CACHE_SECONDS old (PR #63 review)
    assert "{{.Image}} {{.State.Running}}" in smoke  # the containers run exactly the recorded image (its resolved id)
    deploy = (ADAPTERS / "deploy.sh").read_text()
    assert "compose exec -T web" not in deploy  # never through the serving release: during a revert it is the broken one
    assert 'in_image "$serving"' not in deploy and "recorded_forward_only" in deploy  # the record, never the serving image's
    assert "release blockers" in deploy and "restore instead" in deploy
    assert "|| serving_fwd=" not in deploy  # nothing unreadable becomes an empty list (PR #73 review)
    for gate in ("RestartCount", "CATALYST_WORKER_HEARTBEAT_FILE", "migrations_pending", 'image_label "$expected"'):
        assert gate in smoke, gate  # the smoke is the promotion gate
    assert 'org.opencontainers.image.revision"}}' in (ADAPTERS / "lib.sh").read_text()  # image_label reads the OCI label
    predeploy = (ADAPTERS / "predeploy.sh").read_text()
    assert "CATALYST_BACKUP_CMD:?" in predeploy and '[ -e "$receipt" ]' in predeploy  # no backup receipt, no migration
    assert predeploy.index('record_forward_only "$target"') < predeploy.index("run --rm --no-deps migrate")  # record first
    lib_text = (ADAPTERS / "lib.sh").read_text()
    assert 'elif [ -s "$POINTER" ]; then fail' in lib_text  # a lost record is refused while a release serves


SHA_A, SHA_B = "a" * 40, "b" * 40
IMAGE_N, IMAGE_N1, IMAGE_X = "sha256:" + "1" * 64, "sha256:" + "2" * 64, "sha256:" + "f" * 64


def receipt_file(tmp_path, name, mtime, text='{"synthetic": true}\n'):
    path = tmp_path / name
    path.write_text(text)
    os.utime(path, (mtime, mtime))
    return path


def test_9kg_37_an_operation_binds_only_a_backup_taken_for_it_and_refuses_a_stale_or_missing_one(tmp_path):
    """TEST-P6-24: the pre-deploy backup is bound to the operation by the deploy id, the receipt's digest and its
    time; a receipt older than the operation (a backup command printing an older receipt's path) is refused."""
    state = tmp_path / "state"
    operation = release.start_operation(state, "deploy-1", IMAGE_N1, SHA_A, IMAGE_N, now=1_000_000)
    assert operation["started_at"] == 1_000_000 and operation["started_at_utc"] == "1970-01-12T13:46:40+00:00"
    assert release.read_operation(state, "deploy-1") == operation
    with pytest.raises(release.OperationError, match="no receipt that exists"):
        release.bind_backup(state, "deploy-1", tmp_path / "absent.json", now=1_000_005)
    with pytest.raises(release.OperationError, match="stale"):
        release.bind_backup(state, "deploy-1", receipt_file(tmp_path, "older.json", 999_999), now=1_000_005)
    assert release.read_binding(state, "deploy-1") is None  # a refused receipt binds nothing
    fresh = receipt_file(tmp_path, "fresh.json", 1_000_003)
    binding = release.bind_backup(state, "deploy-1", fresh, now=1_000_005)
    assert binding == {"deploy_id": "deploy-1", "receipt": str(fresh.resolve()),
                       "receipt_sha256": hashlib.sha256(fresh.read_bytes()).hexdigest(),
                       "backup_finished_at": 1_000_003, "backup_finished_at_utc": "1970-01-12T13:46:43+00:00",
                       "bound_at": 1_000_005}
    assert release.read_binding(state, "deploy-1") == binding
    # Taken in the same second as the operation started is not older than it.
    release.start_operation(state, "deploy-2", IMAGE_N1, SHA_A, IMAGE_N, now=2_000_000)
    assert release.bind_backup(state, "deploy-2", receipt_file(tmp_path, "same.json", 2_000_000))["backup_finished_at"] == 2_000_000


def test_9kg_37_the_gate_allows_only_the_approved_image_with_its_backup_bound_and_the_recorded_revert(tmp_path):
    """TEST-P6-10 and 24: what deploy.sh asks before switching. A mismatch is a refusal, never a recorded deviation."""
    state = tmp_path / "state"
    release.start_operation(state, "deploy-1", IMAGE_N1, SHA_A, IMAGE_N, now=1_000_000)
    assert release.gate(state, "deploy-1", IMAGE_N1, SHA_A) == ("deploy", ["the pre-deploy backup is not bound to deploy deploy-1"])
    fresh = receipt_file(tmp_path, "fresh.json", 1_000_003)
    release.bind_backup(state, "deploy-1", fresh)
    assert release.gate(state, "deploy-1", IMAGE_N1, SHA_A) == ("deploy", [])  # the positive control
    assert release.gate(state, "deploy-1", IMAGE_N1, SHA_B) == ("deploy", [
        f"{IMAGE_N1}'s commit label is not the approved commit of deploy deploy-1"])
    assert release.gate(state, "deploy-1", IMAGE_N, SHA_A) == ("revert", [])  # the wrapper's revert, no expectation
    assert release.gate(state, "deploy-1", IMAGE_X, SHA_A) == ("refused", [
        f"{IMAGE_X} is neither deploy deploy-1's approved image nor its revert target"])
    assert release.gate(state, "deploy-1", IMAGE_X, SHA_A, serving=IMAGE_X) == ("revert", [])  # already serving
    assert release.gate(state, "deploy-1", IMAGE_N1, SHA_A, serving=IMAGE_N) == ("deploy", [])
    with pytest.raises(release.OperationError, match="no deploy operation deploy-9"):
        release.gate(state, "deploy-9", IMAGE_N1, SHA_A)
    # The receipt must still be what was bound: gone, changed, another deploy's or dated before the operation.
    fresh.write_text('{"synthetic": true, "rewritten": true}\n')
    assert release.backup_problems(state, "deploy-1") == ["the pre-deploy backup's receipt is not the one that was bound"]
    fresh.unlink()
    assert release.backup_problems(state, "deploy-1") == ["the pre-deploy backup's receipt no longer exists"]
    release.start_operation(state, "deploy-2", IMAGE_N1, SHA_A, IMAGE_N, now=1_000_100)
    release.bind_backup(state, "deploy-2", receipt_file(tmp_path, "other.json", 1_000_101))
    shutil.copy(release.operation_dir(state, "deploy-2") / "pre-deploy-backup.json", release.operation_dir(state, "deploy-1"))
    assert release.backup_problems(state, "deploy-1") == [
        "the pre-deploy backup is bound to another deploy (deploy-2), not deploy-1"]
    binding = release.operation_dir(state, "deploy-2") / "pre-deploy-backup.json"
    binding.write_text(json.dumps({**json.loads(binding.read_text()), "backup_finished_at": 999_999}))
    assert release.backup_problems(state, "deploy-2") == ["the pre-deploy backup is older than deploy deploy-2 (stale)"]
    assert release.gate(state, "deploy-2", IMAGE_N1, SHA_A)[1] == ["the pre-deploy backup is older than deploy deploy-2 (stale)"]
    # A revert does not need an expectation, and an operation without an approved commit checks no label.
    release.start_operation(state, "deploy-3", IMAGE_N1, None, None, now=1_000_200)
    release.bind_backup(state, "deploy-3", receipt_file(tmp_path, "third.json", 1_000_201))
    assert release.gate(state, "deploy-3", IMAGE_N1, "unknown") == ("deploy", [])
    assert release.gate(state, "deploy-3", IMAGE_N, SHA_A)[0] == "refused"  # no previous recorded: nothing to revert to


def test_9kg_37_a_restarted_operation_takes_a_new_backup_and_bad_ids_or_commits_are_refused(tmp_path):
    state = tmp_path / "state"
    release.start_operation(state, "deploy-1", IMAGE_N1, SHA_A, IMAGE_N, now=1_000_000)
    release.bind_backup(state, "deploy-1", receipt_file(tmp_path, "first.json", 1_000_001))
    release.start_operation(state, "deploy-1", IMAGE_N1, SHA_A, IMAGE_N, now=1_000_500)  # a predeploy retried
    assert release.read_binding(state, "deploy-1") is None
    assert release.backup_problems(state, "deploy-1") == ["the pre-deploy backup is not bound to deploy deploy-1"]
    for bad in ("", "abc", "x" * 65, "a b", "../up", "deploy/1"):
        with pytest.raises(release.OperationError, match="deploy id"):
            release.operation_dir(state, bad)
    with pytest.raises(release.OperationError, match="full 40-character sha"):
        release.start_operation(state, "deploy-2", IMAGE_N1, "main", IMAGE_N)
    (release.operation_dir(state, "deploy-1") / "operation.json").write_text("{not json")
    with pytest.raises(release.OperationError, match="unreadable"):
        release.read_operation(state, "deploy-1")


def test_9kg_37_the_operation_commands_are_the_tested_functions(tmp_path):
    """The adapters run `python -m config.release operation ...`; exit 0 allows, 1 refuses with the reason, 2 is usage."""
    def run(*args):
        return subprocess.run([sys.executable, "-m", "config.release", "operation", *args], cwd=ROOT, capture_output=True,
                              text=True, env={"PATH": "/usr/bin:/bin"}, timeout=30)
    state = str(tmp_path / "state")
    started = run("start", state, "deploy-1", IMAGE_N1, SHA_A, IMAGE_N)
    assert started.returncode == 0 and json.loads(started.stdout)["target"] == IMAGE_N1
    gate = run("gate", state, "deploy-1", IMAGE_N1, SHA_A, "-")
    assert gate.returncode == 1 and gate.stdout == "" and "not bound to deploy deploy-1" in gate.stderr
    older = receipt_file(tmp_path, "older.json", 1_000)
    stale = run("bind", state, "deploy-1", str(older))
    assert stale.returncode == 1 and "stale" in stale.stderr
    fresh = receipt_file(tmp_path, "fresh.json", time.time())
    bound = run("bind", state, "deploy-1", str(fresh))
    assert bound.returncode == 0 and bound.stdout.strip() == str(tmp_path / "state/operations/deploy-1/pre-deploy-backup.json")
    assert run("gate", state, "deploy-1", IMAGE_N1, SHA_A, "-").stdout.strip() == "deploy"
    assert run("gate", state, "deploy-1", IMAGE_N1, SHA_A, IMAGE_N).stdout.strip() == "deploy"
    assert run("gate", state, "deploy-1", IMAGE_N, SHA_B).stdout.strip() == "revert"
    refused = run("gate", state, "deploy-1", IMAGE_X, SHA_A, "-")
    assert refused.returncode == 1 and "neither deploy deploy-1's approved image nor its revert target" in refused.stderr
    assert run("gate", state, "deploy-1", IMAGE_X, SHA_A, IMAGE_X).stdout.strip() == "revert"
    mismatch = run("gate", state, "deploy-1", IMAGE_N1, SHA_B, "-")
    assert mismatch.returncode == 1 and "not the approved commit" in mismatch.stderr
    shown = json.loads(run("show", state, "deploy-1").stdout)
    assert shown["expected_commit"] == SHA_A and shown["pre_deploy_backup"]["deploy_id"] == "deploy-1"
    assert run("start", state, "deploy-1", "x").returncode == 2 and run("nonsense").returncode == 2
    assert run("gate", state, "deploy-7", IMAGE_N1, SHA_A, "-").returncode == 1
    assert "@" not in (started.stdout + bound.stdout + run("show", state, "deploy-1").stdout)  # identities and times only


def test_9kg_37_the_adapters_gate_on_the_operation_before_switching_and_the_smoke_decides_the_receipt():
    """D-I built as recommended: the receipt is a gate. Every comparison the receipt records is decided before
    promotion: identity and the bound backup in deploy.sh (before compose up), readback and check --deploy in
    smoke.sh; receipt.sh records, and no adapter but predeploy.sh reads the approved commit from the environment."""
    deploy = (ADAPTERS / "deploy.sh").read_text()
    assert deploy.index('operation gate "$target" "$label" "$serving"') < deploy.index("recorded_forward_only") \
        < deploy.index("compose up -d")
    assert "nothing changed" in deploy and 'CATALYST_DEPLOY_ID:?' in deploy
    predeploy = (ADAPTERS / "predeploy.sh").read_text()
    assert predeploy.index("not the approved commit") < predeploy.index("operation start") \
        < predeploy.index('bash -c "$CATALYST_BACKUP_CMD"') < predeploy.index('operation bind "$receipt"') \
        < predeploy.index('record_forward_only "$target"') < predeploy.index("run --rm --no-deps migrate")
    smoke = (ADAPTERS / "smoke.sh").read_text()
    assert "check --deploy --fail-level WARNING" in smoke and "operation show" in smoke
    assert 'o["target"] == sys.argv[2]' in smoke  # the approved commit binds the operation's target, never a revert
    receipt = (ADAPTERS / "receipt.sh").read_text()
    assert 'operation gate "$image" "$label" -' in receipt and '"pre_deploy_backup"' in receipt and '"deploy_id"' in receipt
    for name in ("deploy.sh", "smoke.sh", "receipt.sh", "capture.sh", "lib.sh"):
        text = "\n".join(line for line in (ADAPTERS / name).read_text().splitlines() if not line.startswith("#"))
        assert "CATALYST_EXPECTED_COMMIT" not in text, name
    assert "CATALYST_BACKUP_RECEIPT" not in receipt


def drill_migration(name: str) -> str:
    drill = (ROOT / "scripts" / "deploy_drill.sh").read_text()
    return re.search(rf"^{name}='(.*?)'\n", drill, flags=re.M | re.S).group(1)


def test_9kg_38_the_drill_reverts_n_plus_one_to_n_on_the_expanded_schema_and_refuses_the_contract_revert(tmp_path):
    """TEST-P6-25: the drill's fixtures are what the design says. Its expand migration is one the contracting scan
    passes (an older image runs on it), its contract migration is one the scan flags (so a release must mark it
    forward-only, as the drill's does), and the script reverts through the wrapper with the data checked."""
    for app in release.APPS:
        (tmp_path / app / "migrations").mkdir(parents=True)
    (tmp_path / "workflow" / "migrations" / "0006_expand.py").write_text(drill_migration("expand_migration"))
    (tmp_path / "workflow" / "migrations" / "0007_contract.py").write_text(drill_migration("contract_migration"))
    assert release.contracting(tmp_path, baseline={}) == {"workflow.0007_contract": ["RemoveField"]}
    drill = (ROOT / "scripts" / "deploy_drill.sh").read_text()
    steps = [drill.index(s) for s in (
        'wrapper "$expand"', 'op revert-to-n', '"$adapters/predeploy.sh" "$n"', 'wrapper "$n"',
        '"$adapters/smoke.sh"\ncheck "the schema was not rolled back', 'FORWARD_ONLY: frozenset[str] = frozenset({\\"workflow.0007_contract\\"})',
        'wrapper "$contract"', 'op revert-across-contract', 'wrapper "$expand"; rc=$?\ncheck "a revert across a forward-only migration is refused',
        'workflow.0007_contract.*restore instead')]
    assert steps == sorted(steps)  # N+1 promoted, reverted to N through the wrapper, then the contract revert refused
    assert drill.count("submit n-") == 3 and '"$(applications)" = "$count"' in drill  # the data is checked, not assumed
    # 9kg.63: intake is invitation-only (9kg.43), so every submission is preceded by the owner's invitation, issued by
    # the owner-run command as the migration owner, and a refused invitation fails the submission's check.
    submit = drill[drill.index("\nsubmit() {"):drill.index("\n}\n", drill.index("\nsubmit() {"))]
    invite = drill[drill.index("\ninvite() {"):drill.index("\n}\n", drill.index("\ninvite() {"))]
    assert submit.index('invite "$1" || return 1') < submit.index("curl ")
    assert "run --rm --no-deps -T migrate python manage.py catalyst_invite" in invite and '"issued": true' in invite
    assert "drill_note" in drill_migration("expand_migration") and "null=True" in drill_migration("expand_migration")


def test_6b10_the_image_workflow_attests_only_main_and_pushes_nowhere():
    workflow = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    for uses in re.findall(r"uses: (\S+)", workflow):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses), uses  # every action pinned by commit
    build, attest = workflow.split("\n  attest:\n")
    assert "id-token" not in build and "attestations" not in build  # pull-request runs hold no signing permission
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in attest
    assert "id-token: write" in attest and "subject-path: catalyst-image.tar" in attest
    assert "push-to-registry" not in workflow
    assert "docker push" not in workflow and "docker login" not in workflow
    assert "severity-cutoff: high" in workflow and "fail-build: true" in workflow
    verify = (ROOT / "scripts" / "verify_image_attestation.sh").read_text()
    for flag in ("--signer-workflow \"$repo/.github/workflows/image.yml\"", "--source-ref refs/heads/main",
                 "--source-digest \"$commit\"", "--deny-self-hosted-runners"):
        assert flag in verify, flag
    # The private copy is the one verified and the one loaded (no swap between them); no unattested id file is trusted.
    assert 'gh attestation verify "$tar"' in verify and 'docker load -i "$tar"' in verify and 'tar="$private/image.tar"' in verify
    assert "catalyst-image.id" not in verify
