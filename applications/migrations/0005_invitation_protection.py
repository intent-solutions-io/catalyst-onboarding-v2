# 9kg.43 (029 sections 4.1 and 7; ADR-14). Runs as the migration owner.
#
# Only the owner-run command inserts an invitation: the application role gets no INSERT, so neither a model, a web
# request nor a routine operator can issue one. The application role may consume it (used_at, application_id) and the
# owner may supersede it; identity, issuer, note and expiry are fixed, use and supersession are written once, nothing is
# ever deleted, and the table cannot be truncated. The retention and backup roles read it.
from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants

TABLE = "applications_invitation"

grant_forward, grant_reverse = apply_grants({
    TABLE: {"app": ["SELECT", "UPDATE (used_at, application_id, updated_at)"], "retention": ["SELECT"], "backup": ["SELECT"]},
})

FUNCTION = "catalyst_invitation_fixed"
BODY = """
    BEGIN
      IF TG_OP = 'DELETE'
         OR (NEW.id, NEW.public_id, NEW.email_key, NEW.issued_by, NEW.note, NEW.issued_at, NEW.expires_at)
            IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.email_key, OLD.issued_by, OLD.note, OLD.issued_at, OLD.expires_at)
         OR (OLD.used_at IS NOT NULL AND NEW.used_at IS DISTINCT FROM OLD.used_at)
         OR (OLD.superseded_at IS NOT NULL AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at)
         OR (OLD.application_id IS NOT NULL AND NEW.application_id IS DISTINCT FROM OLD.application_id) THEN
        RAISE EXCEPTION 'invitation: % refused (identity, issuer and expiry are fixed; use and supersession are written once)', TG_OP
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END"""


def backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{TABLE}_id_seq TO {role}")


def no_backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM {role}")


def protect(apps, schema_editor):
    schema_editor.execute(f"CREATE FUNCTION public.{FUNCTION}() RETURNS trigger LANGUAGE plpgsql "
                          f"SET search_path = public, pg_temp AS $$ {BODY} $$", params=None)
    schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{FUNCTION}() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER {FUNCTION} BEFORE UPDATE OR DELETE ON public.{TABLE} "
                          f"FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{TABLE} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{TABLE}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {FUNCTION} ON public.{TABLE}")
    schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{FUNCTION}()")


class Migration(migrations.Migration):
    dependencies = [("applications", "0004_invitation"), ("workflow", "0003_backup_role_reads")]
    operations = [migrations.RunPython(grant_forward, grant_reverse), migrations.RunPython(backup_sequence, no_backup_sequence),
                  migrations.RunPython(protect, unprotect)]
