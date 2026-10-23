"""9kg.30 (029 sections 5.2 and 7; accounts.roles): the append-only record of every staff role grant and revocation.

Runs as the migration owner. The record is written only by the owner-run `grant_staff_role` command (the owner
role); the application role reads it (SELECT) and nothing else, so the running application can never grant itself
a role or hide one it was given (D-23). Rows are protected history for every role, the owner included: the strict
append-only and no-truncate triggers (the functions applications 0002 created). The backup role reads the table
and its sequence (6B.6): a restore brings the grant history back with the accounts it describes.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

from config.db_roles import apply_grants

TABLE = "accounts_staffrolegrant"

grant_forward, grant_reverse = apply_grants({TABLE: {"app": ["SELECT"], "backup": ["SELECT"]}})


def backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{TABLE}_id_seq TO {role}")


def no_backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM {role}")


def protect(apps, schema_editor):
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{TABLE} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{TABLE} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{TABLE}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{TABLE}")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_request_throttle"),
        ("applications", "0003_protect_version_adoption"),  # the strict append-only function (0002) and the S1 chain
    ]
    operations = [
        migrations.CreateModel(
            name="StaffRoleGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(max_length=40)),
                ("kind", models.CharField(choices=[("group", "Group"), ("permission", "Permission")], max_length=16)),
                ("target", models.CharField(max_length=150)),
                ("action", models.CharField(choices=[("grant", "Grant"), ("revoke", "Revoke")], max_length=8)),
                ("approval_ref", models.CharField(max_length=200)),
                ("actor_ref", models.CharField(max_length=200)),
                ("recorded_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="role_grants",
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("action__in", ["grant", "revoke"])),
                                           name="staff_role_grant_action_valid"),
                    models.CheckConstraint(condition=models.Q(("kind__in", ["group", "permission"])),
                                           name="staff_role_grant_kind_valid"),
                    models.CheckConstraint(condition=models.Q(("approval_ref", ""), _negated=True),
                                           name="staff_role_grant_has_approval"),
                ],
            },
        ),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequence, no_backup_sequence),
        migrations.RunPython(protect, unprotect),
    ]
