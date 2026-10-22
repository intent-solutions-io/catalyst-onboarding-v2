"""Release bookkeeping for the deploy adapters (026 section 4; 6B.10). Importable without Django settings, so a
candidate image can say which migrations it knows with no database and no secret:

    python -m config.release known        # JSON: every migration this image carries, "app.name"
    python -m config.release forward-only # JSON: the migrations this image marks forward-only

**Expand, then contract (026 section 4).** Every release must run on the previous release's schema and the previous
release must run on its schema: Django ignores an applied migration it does not know, so reverting the image is
safe. A migration that breaks that rule is listed in FORWARD_ONLY by the release that adds it; once it is applied, the
deploy adapter refuses to switch to any image that does not know it, and the only way back is a restore.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ("accounts", "agreements", "applications", "assessments", "correspondence", "provisioning", "workflow")

# "app.migration_name" for every migration that an image without it cannot run against. Empty: no release so far has
# needed one (every migration to date adds tables, columns with defaults, grants or triggers).
FORWARD_ONLY: frozenset[str] = frozenset()


def known() -> list[str]:
    """Every migration of the Catalyst apps in this tree, "app.name", sorted."""
    return sorted(f"{app}.{path.stem}" for app in APPS for path in (ROOT / app / "migrations").glob("[0-9]*.py"))


def blockers(applied, target_known, forward_only) -> list[str]:
    """Forward-only migrations already applied that the target image does not know: switching to it is refused."""
    return sorted(set(applied) & set(forward_only) - set(target_known))


def main(argv) -> int:
    if argv == ["known"]:
        print(json.dumps(known()))
    elif argv == ["forward-only"]:
        print(json.dumps(sorted(FORWARD_ONLY)))
    else:
        print("usage: python -m config.release known|forward-only", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
