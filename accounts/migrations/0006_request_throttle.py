"""9kg.29 (029 section 4.1; REQ-027): the public-endpoint throttle buckets (config.throttle).

Least privilege (ADR-14): the application role creates a bucket, moves its counter and window, and deletes a stale one
(the hourly sweep); the backup role reads the table and its sequence (6B.6). Nothing else touches it. Expand-only:
a new table, so the previous image runs unchanged (config.release).
"""

import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

from config.db_roles import apply_grants

TABLE = "accounts_requestthrottle"

grant_forward, grant_reverse = apply_grants({
    TABLE: {"app": ["SELECT", "INSERT", "UPDATE (count, window_start, updated_at)", "DELETE"], "backup": ["SELECT"]},
})


def backup_sequence(apps, schema_editor):
    """pg_dump reads each sequence's value (workflow 0003): SELECT only, so the role can never draw one."""
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{TABLE}_id_seq TO {role}")


def no_backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM {role}")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_two_factor_grants"), ("workflow", "0003_backup_role_reads")]
    operations = [
        migrations.CreateModel(
            name="RequestThrottle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=64, unique=True)),
                ("count", models.PositiveIntegerField(default=1)),
                ("window_start", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("updated_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
            ],
        ),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequence, no_backup_sequence),
    ]
