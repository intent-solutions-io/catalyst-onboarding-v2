"""Re-apply the durable erasure record to a restored database (9kg.25; 029 section 6.2.1): run by the owner with the
retention role's login, after `catalyst_restore` and `migrate` and before `catalyst_post_restore`.

    manage.py catalyst_erasure_replay --expect-head <identity>:<seq>:<hash>
    manage.py catalyst_erasure_replay --expect-head none      # only when no erasure was ever made

The head is the one the last erasure or handoff printed, kept out of band: a journal that does not hold it (emptied,
replaced, truncated, rolled back) is refused, never read as "no erasures". Every subject the record names is erased
again in the restored tables (erasure.replay); the run ends with an `erasures_replayed` marker that the post-restore
review and lift require. Re-run it after any interruption, or after an erasure made while the restore was held.

Prints one JSON line: counts, the public references of subjects whose restored address differed from the recorded
one or whose erasure is still open, and the journal head. Never an address, a name or a numeric id. Exit 0 when the
replay finished, 1 when refused (the restore stays held)."""

import json

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand

from config import runtime
from erasure import replay, service


class Command(BaseCommand):
    help = "Re-apply every recorded erasure to a restored database (retention role only)."

    def add_arguments(self, parser):
        parser.add_argument("--expect-head", required=True, help="the head printed by the last erasure or handoff, or 'none'")

    def refuse(self, code, detail=()):
        self.stderr.write(f"erasure replay refused: {code}" + (f" ({', '.join(detail)})" if detail else ""))
        raise SystemExit(1)

    def handle(self, *args, expect_head, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            self.refuse("not_a_management_process")
        if getattr(settings, "CATALYST_CUSTODY_WRAPPING_KEY", ""):
            self.refuse("custody_wrapping_key_present")  # as for catalyst_erase: this process holds no custody key
        db = settings.DATABASES["default"]
        try:
            with psycopg.connect(host=db["HOST"], port=db.get("PORT") or "5432", dbname=db["NAME"], user=db["USER"],
                                 password=db["PASSWORD"]) as conn:
                report = replay.replay(conn, expect_head)
        except service.Refused as exc:
            self.refuse(exc.code, exc.detail)
        except psycopg.Error as exc:  # its detail can quote a row: only the class and the code
            self.refuse(f"database_error {type(exc).__name__} {exc.sqlstate or ''}".rstrip())
        self.stdout.write(json.dumps(report, sort_keys=True))
