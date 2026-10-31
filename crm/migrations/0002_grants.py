# bgl.14 (ADR-14). Runs as the migration owner.
#
# An ordinary operational table: the application role reads it, inserts a row per application and updates only the
# columns the projection changes (never the application it belongs to). The retention and backup roles read it; the
# erase function (SECURITY DEFINER) tombstones its subject column.
from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants

TABLE = "crm_twentylink"

grant_forward, grant_reverse = apply_grants({
    TABLE: {"app": ["SELECT", "INSERT", "UPDATE (person_id, link_method, note_id, note_sha256, field_hashes,"
                    " projection_version, projected_at, updated_at)"],
            "retention": ["SELECT"], "backup": ["SELECT"]},
})


def backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{TABLE}_id_seq TO {role}")


def no_backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM {role}")


class Migration(migrations.Migration):
    dependencies = [("crm", "0001_initial")]
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequence, no_backup_sequence),
    ]
