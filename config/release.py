"""Release bookkeeping for the deploy adapters (026 section 4; 6B.10). Importable without Django settings, so a
candidate image can say which migrations it knows with no database and no secret:

    python -m config.release known        # JSON: every migration this image carries, "app.name"
    python -m config.release forward-only # JSON: the migrations this image marks forward-only
    python -m config.release blockers <applied JSON> <target known JSON> <forward-only JSON>

**Expand, then contract (026 section 4).** Every release must run on the previous release's schema and the previous
release must run on its schema: Django ignores an applied migration it does not know, so reverting the image is
safe. A migration that breaks that rule is listed in FORWARD_ONLY by the release that adds it; once it is applied, the
deploy adapter refuses to switch to any image that does not know it, and the only way back is a restore.

**Not left to memory (PR #73 review).** `contracting()` finds every migration with an operation that can break the
previous image (removing, renaming or altering a field or model, a constraint on an existing table, a table
rename). A test fails unless each one is listed in FORWARD_ONLY or in EXPAND_SAFE with the reviewed reason it is not.
RunSQL and RunPython cannot be read this way; their authors and reviewers decide, and the release notes say so.
"""

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ("accounts", "agreements", "applications", "assessments", "correspondence", "provisioning", "workflow")

# "app.migration_name" for every migration that an image without it cannot run against. Empty: no release so far has
# needed one (every migration to date adds tables, columns with defaults, grants or triggers).
FORWARD_ONLY: frozenset[str] = frozenset()
CONTRACTING_OPERATIONS = frozenset({"RemoveField", "DeleteModel", "RenameField", "RenameModel", "AlterField",
                                    "AlterModelTable", "RemoveConstraint", "AddConstraint", "AlterUniqueTogether"})
# Migrations contracting() flags that were reviewed as safe for the previous image, with the reason.
EXPAND_SAFE: dict[str, str] = {
    "agreements.0003_provider_observations": "replaces a status check with a superset; the older image writes only "
                                              "values it knows",
    "agreements.0005_stop_intent_and_replacement": "narrows a unique constraint's condition (allows more rows) and "
                                                    "checks new columns that the older image never writes",
    "correspondence.0003_outbound_foundations": "widens the outbound status choices and their check to a superset",
    "correspondence.0011_reminders_and_staff_messages": "checks the staff_draft column it adds: the previous image "
                                                         "writes no staff messages, and its rows get the column's NULL",
    "correspondence.0013_clarification_and_interpretation": "a unique index on the text_key column it adds, only "
                                                             "where text_key is set; the previous image leaves it ''",
    "correspondence.0016_welcome_kind": "widens the message kind choices and their check to a superset",
}


def known() -> list[str]:
    """Every migration of the Catalyst apps in this tree, "app.name", sorted."""
    return sorted(f"{app}.{path.stem}" for app in APPS for path in (ROOT / app / "migrations").glob("[0-9]*.py"))


def contracting(root: Path = ROOT) -> dict[str, list[str]]:
    """Every migration with an operation that can break the previous image: {"app.name": [operation, ...]}. A
    constraint added to a model the same migration creates is not counted (nothing older uses that table)."""
    found = {}
    for app in APPS:
        for path in sorted((root / app / "migrations").glob("[0-9]*.py")):
            tree = ast.parse(path.read_text())
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and isinstance(n.func.value, ast.Name) and n.func.value.id == "migrations"]
            created = {_keyword(c, "name") for c in calls if c.func.attr == "CreateModel"}
            ops = sorted({c.func.attr for c in calls if c.func.attr in CONTRACTING_OPERATIONS
                          and not (c.func.attr == "AddConstraint" and _keyword(c, "model_name") in created)})
            if ops:
                found[f"{app}.{path.stem}"] = ops
    return found


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
