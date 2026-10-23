"""Release facts read from the database, for the deploy adapters (026 section 4; 6B.10). Run in the serving web
container as the application role; prints JSON, never personal data.

    manage.py catalyst_release applied   # the Catalyst migrations recorded as applied, "app.name"
    manage.py catalyst_release receipt   # commit, schema head per app, held actions per kind, pending migrations
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count

from config.release import APPS, FORWARD_ONLY


def applied() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations WHERE app = ANY(%s) ORDER BY app, name", [list(APPS)])
        return [f"{app}.{name}" for app, name in cursor.fetchall()]


def receipt() -> dict:
    from workflow.models import PendingAction

    executor = MigrationExecutor(connection)
    heads = {}
    for name in applied():
        app, migration = name.split(".", 1)
        heads[app] = max(heads.get(app, ""), migration)
    held = (PendingAction.objects.filter(status=PendingAction.Status.HELD).values("kind").annotate(n=Count("id"))
            .order_by("kind"))
    commit_file = Path(__file__).resolve().parents[3] / "COMMIT"
    from django.conf import settings

    return {
        "commit": commit_file.read_text().strip() if commit_file.exists() else "unknown",
        "schema_heads": heads,
        "migrations_pending": len(executor.migration_plan(executor.loader.graph.leaf_nodes())),
        "held_actions": {row["kind"]: row["n"] for row in held},
        "forward_only": sorted(FORWARD_ONLY),
        "intake_mode": settings.CATALYST_INTAKE_MODE,  # 9kg.43: the receipt is the recorded owner act for the mode
    }


class Command(BaseCommand):
    help = "Print release facts (applied migrations, or the deploy receipt) as JSON."

    def add_arguments(self, parser):
        parser.add_argument("what", choices=("applied", "receipt"))

    def handle(self, *args, what, **options):
        try:
            self.stdout.write(json.dumps(applied() if what == "applied" else receipt(), sort_keys=True))
        except Exception as exc:  # the adapters fail closed on a non-zero exit; the reason, never data
            raise CommandError(f"catalyst_release {what} failed ({type(exc).__name__})") from None
