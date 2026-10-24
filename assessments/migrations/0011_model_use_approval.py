"""oc4.9 (018 section 21): the owner's recorded approval of live model use, checked before any live request.

Runs as the migration owner. The record is written only by the owner-run `approve_model_use` command (the owner
role); the application role reads it (SELECT) and nothing else, so the running application can never approve its own
model use (D-23), and no web path writes it. Rows are protected history for every role, the owner included: the
strict append-only and no-truncate triggers (the functions applications 0002 created). The backup role reads the table
and its sequence (6B.6), like the staff role grant record (accounts 0007).
"""

import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

from config.db_roles import apply_grants

TABLE = "assessments_modeluseapproval"

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
        ("assessments", "0010_decision_inputs_and_human_only_code"),
        ("applications", "0003_protect_version_adoption"),  # the strict append-only function (0002)
    ]
    operations = [
        migrations.CreateModel(
            name="ModelUseApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("purpose", models.CharField(max_length=20)),
                ("action", models.CharField(choices=[("approve", "Approve"), ("revoke", "Revoke")], max_length=8)),
                ("provider", models.CharField(max_length=40)),
                ("model_id", models.CharField(max_length=100)),
                ("terms", models.JSONField(default=dict)),
                ("terms_sha256", models.CharField(max_length=64)),
                ("approval_ref", models.CharField(max_length=200)),
                ("actor_ref", models.CharField(max_length=200)),
                ("recorded_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("purpose__in", ["assessment", "interpretation"])),
                                           name="model_use_purpose_valid"),
                    models.CheckConstraint(condition=models.Q(("action__in", ["approve", "revoke"])),
                                           name="model_use_action_valid"),
                    models.CheckConstraint(condition=models.Q(("approval_ref", ""), _negated=True),
                                           name="model_use_has_approval_ref"),
                ],
            },
        ),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequence, no_backup_sequence),
        migrations.RunPython(protect, unprotect),
    ]
