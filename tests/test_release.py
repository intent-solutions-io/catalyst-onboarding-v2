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
    assert "{{.Config.Image}}" in smoke  # the containers must run exactly the recorded image
    deploy = (ADAPTERS / "deploy.sh").read_text()
    assert "compose exec -T web" not in deploy  # never through the serving release: during a revert it is the broken one
    assert "restore instead" in deploy
    predeploy = (ADAPTERS / "predeploy.sh").read_text()
    assert "CATALYST_BACKUP_CMD:?" in predeploy  # no backup, no migration


def test_6b10_the_image_workflow_attests_only_main_and_pushes_nowhere():
    workflow = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    for uses in re.findall(r"uses: (\S+)", workflow):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses), uses  # every action pinned by commit
    attest = workflow[workflow.index("- name: Attest the image tarball"):]
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in attest.split("uses:")[0]
    assert "subject-path: catalyst-image.tar" in attest and "push-to-registry" not in workflow
    assert "docker push" not in workflow and "docker login" not in workflow
    assert "severity-cutoff: high" in workflow and "fail-build: true" in workflow
    verify = (ROOT / "scripts" / "verify_image_attestation.sh").read_text()
    for flag in ("--signer-workflow \"$repo/.github/workflows/image.yml\"", "--source-ref refs/heads/main",
                 "--source-digest \"$commit\"", "--deny-self-hosted-runners"):
        assert flag in verify, flag
