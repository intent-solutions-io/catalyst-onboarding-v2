"""6B.10 (026 sections 4 and 9; TEST-P6-17 to 20): release bookkeeping, the deploy adapters' rules, and the image
workflow. The adapters themselves are driven by the estate deploy wrapper in scripts/deploy_drill.sh on the dev box
(a good release promoted, a broken one reverted, a forward-only revert refused)."""

import json
import re
import subprocess
import sys
from io import StringIO

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
    assert release.contracting(tmp_path) == {"workflow.0099_drop": ["RemoveField"]}


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
    assert receipt["migrations_pending"] == 0 and receipt["schema_heads"]["workflow"] == "0004_restore_hold_protection"
    assert set(receipt) == {"commit", "schema_heads", "migrations_pending", "held_actions", "forward_only"}
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
    assert 'in_image "$serving"' not in deploy and "FORWARD_ONLY_STATE" in deploy  # the recorded list, never the serving image's
    assert "release blockers" in deploy and "restore instead" in deploy
    assert "|| serving_fwd=" not in deploy  # nothing unreadable becomes an empty list (PR #73 review)
    for gate in ("RestartCount", "CATALYST_WORKER_HEARTBEAT_FILE", "migrations_pending", "org.opencontainers.image.revision"):
        assert gate in smoke, gate  # the smoke is the promotion gate
    predeploy = (ADAPTERS / "predeploy.sh").read_text()
    assert "CATALYST_BACKUP_CMD:?" in predeploy and '[ -e "$receipt" ]' in predeploy  # no backup receipt, no migration


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
