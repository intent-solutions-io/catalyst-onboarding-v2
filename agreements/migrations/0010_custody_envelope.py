# 9kg.34 (026 section 6 option c; council 030 Q3 and Q4, D-51). Runs as the migration owner.
#
# The custody envelope: one row per sealed document (agreements.keystore), naming the sealed file, the data key's
# reference and the sealed bytes' digest and size. It holds no key material. Like the stored document it describes,
# it is history: the application role may insert and read it, the retention and backup roles read it, and the strict
# append-only and no-truncate triggers refuse every change for every role. Expand-only: a new table, nothing removed or
# renamed, so the previous image runs on it unchanged (it never reads the table, and its plaintext reads still work
# for documents without an envelope).
import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

from config.db_roles import apply_grants

TABLE = "agreements_custodyenvelope"

grant_forward, grant_reverse = apply_grants({TABLE: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"],
                                                     "backup": ["SELECT"]}})


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
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{TABLE}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{TABLE}")


class Migration(migrations.Migration):

    dependencies = [
        ("agreements", "0009_staff_groups"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustodyEnvelope",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("storage_key", models.CharField(max_length=80, unique=True)),
                ("scheme", models.CharField(max_length=32)),
                ("key_ref", models.CharField(max_length=32, unique=True)),
                ("wrapping_key_id", models.CharField(max_length=16)),
                ("cipher_sha256", models.CharField(max_length=64)),
                ("cipher_size", models.PositiveIntegerField()),
                ("migrated", models.BooleanField(default=False)),
                (
                    "sealed_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now()
                    ),
                ),
                (
                    "document",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="envelope",
                        to="agreements.storeddocument",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("scheme", "aes-256-gcm/v1")),
                        name="custody_envelope_scheme_known",
                    )
                ],
            },
        ),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequence, no_backup_sequence),
        migrations.RunPython(protect, unprotect),
    ]
