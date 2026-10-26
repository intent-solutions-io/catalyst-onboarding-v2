"""The erasure-replay leg of the restore drill (9kg.25; scripts/restore_drill.sh): synthetic only, refused outside the
`test` and `staging` environments.

    manage.py catalyst_erasure_drill erase  --subject <public ref> --storage-dir D --key-dir K --mirror-dir M
    manage.py catalyst_erasure_drill replay --expect-head <head>
    manage.py catalyst_erasure_drill trace  --needle <text>

The shipped registry (erasure.registry) stays undecided until POL-10, so the real commands refuse every erasure. For
its own run only, this command installs a decided synthetic registry (every subject class anonymized, the custody copy
under `destroy_key`) and then calls the real command, unchanged:

- `erase` runs `catalyst_erase` (the retention login, the erasure key, the custody directories named on the command
  line as for `catalyst_custody_drill`, never the wrapping key) and prints its line;
- `replay` runs `catalyst_erasure_replay` (the retention login, the erasure key) and prints its line;
- `trace` counts, as the owner, the rows of every public table but the staff sessions whose text holds `--needle` (a
  synthetic address), so the drill shows the subject back after the restore and gone after the replay.

Output is one JSON line; nothing printed is personal (the data is synthetic and only counts are printed by `trace`).
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from config.guards import synthetic
from erasure import registry

SYNTHETIC = {
    **{name: {"treatment": registry.ANONYMIZE, "retention": "synthetic-drill"} for name in registry.SUBJECT_CLASSES},
    "signed_documents": {"treatment": registry.DESTROY_KEY, "retention": "synthetic-drill"},
    "provider_copies": {"treatment": registry.MANUAL_HANDOFF, "retention": "synthetic-drill"},
    "erasure_record": {"treatment": registry.RETAIN, "retention": "synthetic-drill-oldest-backup"},
    "effect_journal": {"treatment": registry.RETAIN, "retention": "synthetic-drill-oldest-backup"},
}


class Command(BaseCommand):
    help = "The synthetic erasure-replay leg of the restore drill (9kg.25)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("erase", "replay", "trace"))
        parser.add_argument("--subject", default="")
        parser.add_argument("--expect-head", default="")
        parser.add_argument("--needle", default="")
        parser.add_argument("--storage-dir", default="")
        parser.add_argument("--key-dir", default="")
        parser.add_argument("--mirror-dir", default="")

    def handle(self, *args, action, subject, expect_head, needle, storage_dir, key_dir, mirror_dir, **options):
        if not synthetic(getattr(settings, "CATALYST_ENV", "")):
            raise CommandError("the erasure drill runs only in the test and staging environments (synthetic data)")
        if action == "trace":
            if len(needle) < 12:
                raise CommandError("--needle must be a synthetic marker of at least 12 characters")
            self.stdout.write(json.dumps(trace(needle), sort_keys=True))
            return
        registry.REGISTRY = SYNTHETIC  # this process only: the shipped registry is unchanged
        if action == "erase":
            for value in (storage_dir, key_dir, mirror_dir):
                if not Path(value).is_absolute():
                    raise CommandError("the drill's custody directories must be absolute paths")
            settings.CATALYST_AGREEMENT_STORAGE_DIR = storage_dir
            settings.CATALYST_CUSTODY_KEY_DIR = key_dir
            settings.CATALYST_CUSTODY_KEY_MIRROR_DIR = mirror_dir
            call_command("catalyst_erase", "--subject", subject, "--authority", "drill:synthetic-decision",
                         "--reason", "drill-erasure", stdout=self.stdout, stderr=self.stderr)
        else:
            call_command("catalyst_erasure_replay", "--expect-head", expect_head, stdout=self.stdout, stderr=self.stderr)


def trace(needle: str) -> dict:
    rows = tables = 0
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'django_session'")
        for (table,) in cursor.fetchall():
            cursor.execute(f"SELECT count(*) FROM public.{connection.ops.quote_name(table)} t WHERE t::text ILIKE %s",
                           [f"%{needle}%"])
            found = cursor.fetchone()[0]
            rows, tables = rows + found, tables + int(bool(found))
    return {"rows": rows, "tables": tables}
