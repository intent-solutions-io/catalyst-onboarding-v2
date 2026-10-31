"""Release bookkeeping for the deploy adapters (026 section 4; 6B.10). Importable without Django settings, so a
candidate image can say which migrations it knows with no database and no secret:

    python -m config.release known        # JSON: every migration this image carries, "app.name"
    python -m config.release forward-only # JSON: the migrations this image marks forward-only
    python -m config.release blockers <applied JSON> <target known JSON> <forward-only JSON>

**Expand, then contract (026 section 4).** Every release must run on the previous release's schema and the previous
release must run on its schema: Django ignores an applied migration it does not know, so reverting the image is
safe. A migration that breaks that rule is listed in FORWARD_ONLY by the release that adds it; once it is applied, the
deploy adapter refuses to switch to any image that does not know it, and the only way back is a restore.

**Not left to memory (PR #73 review).** `contracting()` finds every migration after BASELINE with an operation that can
break the previous image (removing, renaming or altering a field or model, a constraint on an existing table, a
NOT NULL column without a database default, a table rename). A test fails unless each one is listed in FORWARD_ONLY
or in EXPAND_SAFE with the reviewed reason it is not.
RunSQL and RunPython cannot be read this way; their authors and reviewers decide, and the release notes say so.

**The deploy operation (PL batch 2, bead 9kg.37; D-I built on its recommended default, the receipt as a gate).** Every
deploy is one operation, named by a deploy id the caller chooses (the force-command), recorded under
`<deploy state>/operations/<id>/`:

    python -m config.release operation start <state> <id> <target image> <approved commit|-> <previous image|->
    python -m config.release operation bind  <state> <id> <backup receipt path>   # refuses a stale receipt
    python -m config.release operation gate  <state> <id> <image> <image's commit label>   # prints deploy|revert
    python -m config.release operation show  <state> <id>                        # JSON: operation + binding

`start` records the approved artifact (the target image and its approved commit) and the serving image the operation
would revert to. `bind` ties the pre-deploy backup to the operation: the receipt's path, its SHA-256 and its time
(the file's modification time), refusing a receipt older than the operation. `gate` is what deploy.sh asks before
switching: the operation's target may switch only with its commit label approved and its backup bound, present,
unchanged, this operation's and not stale; the operation's previous image may switch back (the wrapper's revert);
anything else is refused. Nothing here is advisory: a problem is a refusal, and the wrapper then reverts and holds.
"""

import ast
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ("accounts", "agreements", "applications", "assessments", "correspondence", "erasure", "firstgen", "provisioning",
        "workflow")
DEPLOY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{3,63}")
COMMIT = re.compile(r"[0-9a-f]{40}")

# "app.migration_name" for every migration that an image without it cannot run against. Empty: no release so far has
# needed one (every migration to date adds tables, nullable or database-defaulted columns, grants or triggers; the
# contracting scan and EXPAND_SAFE below are the record).
FORWARD_ONLY: frozenset[str] = frozenset()
CONTRACTING_OPERATIONS = frozenset({"RemoveField", "DeleteModel", "RenameField", "RenameModel", "AlterField",
                                    "AlterModelTable", "RemoveConstraint", "AddConstraint", "AlterUniqueTogether"})
# The baseline: every migration up to these existed when the deploy guard arrived (6B.10). No image without them can
# ever serve, because deploy.sh refuses an image that cannot answer config.release, which every older image is; so a
# revert can never reach a schema they changed, and contracting() starts after them. (They were not all expand-safe:
# correspondence.0013 added NOT NULL columns with Python-only defaults. It does not matter only for this reason.)
BASELINE: dict[str, str] = {
    "accounts": "0005_two_factor_grants", "agreements": "0008_custody_and_details_protection",
    "applications": "0003_protect_version_adoption", "assessments": "0009_fetcher_role_grants",
    "correspondence": "0016_welcome_kind", "provisioning": "0006_revocation_and_withdrawal_protection",
    "workflow": "0004_restore_hold_protection",
    "erasure": "",  # 9kg.32: the app came after the guard, so every one of its migrations is scanned
}
# Later migrations that contracting() flags but a reviewer found safe for the previous image, with the reason.
EXPAND_SAFE: dict[str, str] = {
    "assessments.0010_decision_inputs_and_human_only_code": (
        "adds columns with database defaults and a CHECK constraint created NOT VALID: a previous image inserts decisions "
        "without the new columns (defaults fill them) and never a human-only row without a code it does not know, because "
        "its human-only rows are refused by the decision service's digest check first; nothing is removed or renamed"),
    "applications.0009_tombstone_keys_unique": (
        "adds three partial unique indexes on email keys that start with `erased:` (9kg.32): no key has that form until "
        "an erasure writes one, and a previous image never writes one, so it cannot violate them; nothing is removed, "
        "renamed or made stricter for any row a previous image writes"),
    "correspondence.0019_decline_notice": (
        "widens the approved-message kind CHECK and the field's choices by one value (`decline`); the choices change is "
        "state only, and every row a previous image writes already satisfies the wider CHECK. A previous image that "
        "meets a `decline` row skips its send as `application_closed` and never claims `send_decline` (no handler), so "
        "a revert sends nothing it should not; nothing is removed or renamed. Reversing the migration itself (not "
        "needed to run a previous image) needs no `decline` rows, because the narrower CHECK would refuse them; its "
        "reverse step returns the `send_decline` rows it cancelled to held"),
}


def known() -> list[str]:
    """Every migration of the Catalyst apps in this tree, "app.name", sorted."""
    return sorted(f"{app}.{path.stem}" for app in APPS for path in (ROOT / app / "migrations").glob("[0-9]*.py"))


def contracting(root: Path = ROOT, baseline: dict | None = None) -> dict[str, list[str]]:
    """Every migration after `baseline` (BASELINE by default; {} for all) with an operation that can break the previous
    image: {"app.name": [operation, ...]}. A constraint or column added to a model the same migration creates is not
    counted (nothing older uses that table)."""
    baseline = BASELINE if baseline is None else baseline
    found = {}
    for app in APPS:
        for path in sorted((root / app / "migrations").glob("[0-9]*.py")):
            if path.stem <= baseline.get(app, ""):
                continue  # in every deployable image (BASELINE)
            tree = ast.parse(path.read_text())
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and isinstance(n.func.value, ast.Name) and n.func.value.id == "migrations"]
            created = {_keyword(c, "name") for c in calls if c.func.attr == "CreateModel"}
            ops = {c.func.attr for c in calls if c.func.attr in CONTRACTING_OPERATIONS
                   and not (c.func.attr == "AddConstraint" and _keyword(c, "model_name") in created)}
            # A NOT NULL column with no database default on an existing table: Django drops a plain `default=` from
            # the database after adding it, so the previous image's inserts would fail (PR #73 re-review).
            ops |= {"AddField" for c in calls if c.func.attr == "AddField" and _keyword(c, "model_name") not in created
                    and _required_without_db_default(c)}
            ops = sorted(ops)
            if ops:
                found[f"{app}.{path.stem}"] = ops
    return found


def _required_without_db_default(add_field) -> bool:
    field = next((k.value for k in add_field.keywords if k.arg == "field"), None)
    if not isinstance(field, ast.Call):
        return True  # unreadable: count it, and let a reviewer record it
    options = {k.arg: k.value for k in field.keywords}
    nullable = isinstance(options.get("null"), ast.Constant) and options["null"].value is True
    many = isinstance(field.func, ast.Attribute) and field.func.attr == "ManyToManyField"
    return not (nullable or many or "db_default" in options)


def _keyword(call, name):
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value).lower()
    return None


def blockers(applied, target_known, forward_only) -> list[str]:
    """Forward-only migrations already applied that the target image does not know: switching to it is refused."""
    return sorted(set(applied) & set(forward_only) - set(target_known))


class OperationError(Exception):
    """A deploy operation that cannot proceed; the message is the refusal, with no data in it."""


def operation_dir(state: Path, deploy_id: str) -> Path:
    if not DEPLOY_ID.fullmatch(deploy_id):
        raise OperationError("refused: the deploy id must be 4 to 64 characters of letters, digits, '.', '_' or '-'")
    return Path(state) / "operations" / deploy_id


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _read_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OperationError(f"refused: {what} is unreadable ({type(exc).__name__})") from None


def _utc(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def start_operation(state: Path, deploy_id: str, target: str, expected_commit: str | None, previous: str | None,
                    now: float | None = None) -> dict:
    """Record the approved artifact and the revert target, before the backup, so the backup can be dated against the
    operation. A deploy id names one operation; starting it again (a predeploy retried after its backup failed)
    replaces the record and drops any earlier binding, so a retried operation always takes a new backup."""
    if expected_commit is not None and not COMMIT.fullmatch(expected_commit):
        raise OperationError("refused: the approved commit must be a full 40-character sha")
    directory = operation_dir(state, deploy_id)
    directory.mkdir(parents=True, exist_ok=True)
    started = int(time.time() if now is None else now)
    operation = {"deploy_id": deploy_id, "target": target, "expected_commit": expected_commit, "previous": previous,
                 "started_at": started, "started_at_utc": _utc(started)}
    binding = directory / "pre-deploy-backup.json"
    if binding.exists():
        binding.unlink()
    _write_json(directory / "operation.json", operation)
    return operation


def read_operation(state: Path, deploy_id: str) -> dict:
    path = operation_dir(state, deploy_id) / "operation.json"
    if not path.is_file():
        raise OperationError(f"refused: no deploy operation {deploy_id}; run predeploy.sh for it first")
    return _read_json(path, f"deploy {deploy_id}'s record")


def read_binding(state: Path, deploy_id: str) -> dict | None:
    path = operation_dir(state, deploy_id) / "pre-deploy-backup.json"
    return _read_json(path, f"deploy {deploy_id}'s backup binding") if path.is_file() else None


def bind_backup(state: Path, deploy_id: str, receipt: Path, now: float | None = None) -> dict:
    """Bind the pre-deploy backup to the operation: the receipt the backup command printed must exist and be no older
    than the operation (a backup command that prints an older receipt's path is refused: that backup is not this
    deploy's). The binding is the pre-deploy backup receipt the deploy side keeps: the deploy id, the receipt's
    path, its digest and its time."""
    operation = read_operation(state, deploy_id)
    receipt = Path(receipt)
    if not receipt.is_file():
        raise OperationError("refused: the pre-deploy backup printed no receipt that exists")
    finished = int(receipt.stat().st_mtime)
    if finished < operation["started_at"]:
        raise OperationError(f"refused: the pre-deploy backup's receipt is older than deploy {deploy_id} (stale, from "
                             f"{_utc(finished)}; the deploy started {operation['started_at_utc']}); take a new backup")
    binding = {"deploy_id": deploy_id, "receipt": str(receipt.resolve()),
               "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
               "backup_finished_at": finished, "backup_finished_at_utc": _utc(finished),
               "bound_at": int(time.time() if now is None else now)}
    _write_json(operation_dir(state, deploy_id) / "pre-deploy-backup.json", binding)
    return binding


def backup_problems(state: Path, deploy_id: str) -> list[str]:
    """Why the operation's pre-deploy backup does not allow a deploy: missing, another deploy's, gone, changed or
    stale. Empty when the backup is bound to this operation and still what was bound."""
    operation = read_operation(state, deploy_id)
    binding = read_binding(state, deploy_id)
    if binding is None:
        return [f"the pre-deploy backup is not bound to deploy {deploy_id}"]
    if binding.get("deploy_id") != deploy_id:
        return [f"the pre-deploy backup is bound to another deploy ({binding.get('deploy_id')}), not {deploy_id}"]
    receipt = Path(binding.get("receipt", ""))
    if not receipt.is_file():
        return ["the pre-deploy backup's receipt no longer exists"]
    if hashlib.sha256(receipt.read_bytes()).hexdigest() != binding.get("receipt_sha256"):
        return ["the pre-deploy backup's receipt is not the one that was bound"]
    if int(binding.get("backup_finished_at", -1)) < operation["started_at"]:
        return [f"the pre-deploy backup is older than deploy {deploy_id} (stale)"]
    return []


def gate(state: Path, deploy_id: str, image: str, label: str, serving: str | None = None) -> tuple[str, list[str]]:
    """What switching to `image` is under this operation: ("deploy", problems) for the operation's target, which may
    switch only with its label equal to the approved commit and its backup bound; ("revert", []) for the operation's
    previous image, the wrapper's revert, which returns to what was recorded; ("refused", [why]) for anything else.
    The image already serving (`serving`, the pointer) is always a revert: it is what the wrapper restores when an
    apply was refused before any switch, and re-applying it changes no identity."""
    if serving and image == serving:
        return "revert", []
    operation = read_operation(state, deploy_id)
    if image == operation["target"]:
        problems = []
        if operation["expected_commit"] and label != operation["expected_commit"]:
            problems.append(f"{image}'s commit label is not the approved commit of deploy {deploy_id}")
        problems += backup_problems(state, deploy_id)
        return "deploy", problems
    if operation["previous"] and image == operation["previous"]:
        return "revert", []
    return "refused", [f"{image} is neither deploy {deploy_id}'s approved image nor its revert target"]


def operation_main(argv) -> int:
    try:
        if len(argv) == 6 and argv[0] == "start":
            _, state, deploy_id, target, expected, previous = argv
            print(json.dumps(start_operation(Path(state), deploy_id, target, None if expected == "-" else expected,
                                             None if previous == "-" else previous), sort_keys=True))
        elif len(argv) == 4 and argv[0] == "bind":
            print(str(operation_dir(Path(argv[1]), argv[2]) / "pre-deploy-backup.json")
                  if bind_backup(Path(argv[1]), argv[2], Path(argv[3])) else "")
        elif len(argv) in (5, 6) and argv[0] == "gate":
            serving = argv[5] if len(argv) == 6 and argv[5] != "-" else None
            role, problems = gate(Path(argv[1]), argv[2], argv[3], argv[4], serving)
            if problems:
                raise OperationError("refused: " + "; ".join(problems))
            print(role)
        elif len(argv) == 3 and argv[0] == "show":
            operation = read_operation(Path(argv[1]), argv[2])
            print(json.dumps({**operation, "pre_deploy_backup": read_binding(Path(argv[1]), argv[2])}, sort_keys=True))
        else:
            return 2
    except OperationError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


USAGE = ("usage: python -m config.release known|forward-only|blockers <applied> <known> <forward-only>\n"
         "       python -m config.release operation start|bind|gate|show ...")


def main(argv) -> int:
    if argv == ["known"]:
        print(json.dumps(known()))
    elif argv == ["forward-only"]:
        print(json.dumps(sorted(FORWARD_ONLY)))
    elif len(argv) == 4 and argv[0] == "blockers":  # the deploy adapter runs this, the tested code
        print(" ".join(blockers(*(json.loads(a) for a in argv[1:]))))
    elif argv[:1] == ["operation"]:  # the deploy adapters run these too
        status = operation_main(argv[1:])
        if status != 2:
            return status
        print(USAGE, file=sys.stderr)
        return 2
    else:
        print(USAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
