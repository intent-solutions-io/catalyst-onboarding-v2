# bgl.16 (035; ADR-14). Runs as the migration owner.
#
# Only the owner-run `catalyst_import_v1` writes these tables: the application role may read them (the dossier and the
# thread lookup, firstgen.threads) and nothing else; the retention and backup roles read them. Every row is
# append-only for every role and no table can be truncated. The record table's `data` is personal history (erasure
# class `history_events`): its trigger is the erasable refusal (erasure 0002), which admits exactly the audited
# tombstone and nothing else. The case and run tables hold nothing personal and keep the strict refusal.
from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants

RUN, CASE, RECORD = "firstgen_importrun", "firstgen_importedcase", "firstgen_importedrecord"
TABLES = (RUN, CASE, RECORD)

grant_forward, grant_reverse = apply_grants({
    table: {"app": ["SELECT"], "retention": ["SELECT"], "backup": ["SELECT"]} for table in TABLES
})


def backup_sequences(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    for table in TABLES:
        schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{table}_id_seq TO {role}")


def no_backup_sequences(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    for table in TABLES:
        schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{table}_id_seq FROM {role}")


def protect(apps, schema_editor):
    for table in TABLES:
        function = "catalyst_erasable_append_only" if table == RECORD else "catalyst_append_only_strict"
        schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{table} "
                              f"FOR EACH ROW EXECUTE FUNCTION public.{function}()")
        schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{table} "
                              "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{table}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{table}")


class Migration(migrations.Migration):
    dependencies = [("firstgen", "0001_initial")]  # 0001 follows erasure 0004, which brings the erasable refusal
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequences, no_backup_sequences),
        migrations.RunPython(protect, unprotect),
    ]
