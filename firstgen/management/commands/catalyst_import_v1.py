"""Convert every record of the first-generation service into this database (bgl.16; 035). Owner only.

    manage.py catalyst_import_v1 --source-dsn "<libpq DSN of the first-generation database>" --run-by "<who>" [--dry-run]

Run as the migration owner: the import writes records the application role may not (member-on-file records, the
import's own provenance), and the command refuses any other login. The source is read in one read-only snapshot and
never written. `--dry-run` does everything inside one transaction and rolls it back. The report (JSON on stdout,
counts, references and codes; never a name, an address or a message) gives, per first-generation table, the rows read,
mapped, already imported and skipped with their reason; per v2 model, the rows created; every state mapping; every
case that failed; and what each in-flight case needs from v2 next (035 section 5). Nothing is queued and nothing is
sent: `--schedule-followups` is refused, because no v2 action can continue a first-generation case without a staff
decision first.

Exit status: 0 everything accounted for; 1 a case failed, a dormant table holds rows, or the source lacks a table;
2 a personal-data row is unaccounted for (dropped without a reason). The DSN is never printed or logged.
"""

import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from firstgen import importer, source

logger = logging.getLogger("firstgen.import")


class _DryRun(Exception):
    pass


class Command(BaseCommand):
    help = "Import the first-generation database (read-only source) into this database; --dry-run rolls back."

    def add_arguments(self, parser):
        parser.add_argument("--source-dsn", required=True, help="libpq connection string of the first-generation database")
        parser.add_argument("--run-by", required=True, help="who runs the import (recorded, never a secret)")
        parser.add_argument("--dry-run", action="store_true", help="do everything in one transaction, then roll back")
        parser.add_argument("--schedule-followups", action="store_true",
                            help="refused: no v2 action continues a first-generation case without a staff decision")

    def handle(self, *args, source_dsn, run_by, dry_run, schedule_followups, **options):
        if schedule_followups:
            raise CommandError("refused (followups_need_staff): the report lists what each case needs; nothing is queued")
        run_by = " ".join(run_by.split())
        if not run_by or len(run_by) > 200:
            raise CommandError("--run-by must name who runs the import (at most 200 characters)")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            login = cursor.fetchone()[0]
        if login != settings.CATALYST_DB_ROLES["owner"]:
            raise CommandError("refused (not_the_owner): run the import as the migration owner")
        try:
            snap = source.read(source_dsn)
        except Exception as exc:  # the DSN may be in the message: report the class only
            raise CommandError(f"refused (source_unreadable): {type(exc).__name__}") from None
        work = importer.Importer(snap, f"owner:{run_by}")
        if dry_run:  # one transaction around everything, rolled back; each person is a savepoint inside it
            try:
                with transaction.atomic():
                    work.run()
                    report = work.report(dry_run)
                    raise _DryRun
            except _DryRun:
                pass
        else:  # one transaction per person (firstgen.importer), then the run's own record
            work.run()
            report = work.report(dry_run)
            with transaction.atomic():
                work.save_run(report)
        self.stdout.write(json.dumps(report, indent=1, sort_keys=True, default=str))
        logger.info("first-generation import %s by %s: %s cases failed", "dry run" if dry_run else "run", run_by,
                    len(report["failures"]))
        if report["personal_rows_dropped_without_reason"]:
            raise CommandError("personal-data rows unaccounted for: see the report", returncode=2)
        problems = [f"{len(report['failures'])} case(s) failed"] if report["failures"] else []
        problems += [f"dormant table {t} holds {n} row(s)" for t, n in report["dormant_rows"].items()]
        problems += [f"source lacks table {t}" for t in report["missing_tables"]]
        if problems:
            raise CommandError("; ".join(problems), returncode=1)
