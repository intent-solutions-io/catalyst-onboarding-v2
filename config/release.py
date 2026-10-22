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
"""

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ("accounts", "agreements", "applications", "assessments", "correspondence", "provisioning", "workflow")

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
}
# Later migrations that contracting() flags but a reviewer found safe for the previous image, with the reason.
EXPAND_SAFE: dict[str, str] = {}


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


def main(argv) -> int:
    if argv == ["known"]:
        print(json.dumps(known()))
    elif argv == ["forward-only"]:
        print(json.dumps(sorted(FORWARD_ONLY)))
    elif len(argv) == 4 and argv[0] == "blockers":  # the deploy adapter runs this, the tested code
        print(" ".join(blockers(*(json.loads(a) for a in argv[1:]))))
    else:
        print("usage: python -m config.release known|forward-only|blockers <applied> <known> <forward-only>",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
