# 9kg.52 (030 Q4 and Q8; ADR-14). Runs as the migration owner.
#
# The member-on-file record: only the owner-run command inserts one (the application role gets SELECT for the dossier
# and nothing else; the retention and backup roles read it). Every column is fixed, supersession is written once,
# nothing is ever deleted and the table cannot be truncated. The invitation's notice record (0007) joins the columns
# its trigger fixes: the function from 0005 is replaced with the two new columns in its list and restored on reverse.
from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants

TABLE = "applications_memberagreementonfile"
INVITATION = "applications_invitation"

grant_forward, grant_reverse = apply_grants({
    TABLE: {"app": ["SELECT"], "retention": ["SELECT"], "backup": ["SELECT"]},
})

FUNCTION = "catalyst_member_on_file_fixed"
BODY = """
    BEGIN
      IF TG_OP = 'DELETE'
         OR (NEW.id, NEW.public_id, NEW.email_key, NEW.agreement_version, NEW.completion_verified, NEW.recorded_by,
             NEW.note, NEW.recorded_at)
            IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.email_key, OLD.agreement_version, OLD.completion_verified,
                              OLD.recorded_by, OLD.note, OLD.recorded_at)
         OR (OLD.superseded_at IS NOT NULL AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at) THEN
        RAISE EXCEPTION 'member on file: % refused (the record is fixed; supersession is written once)', TG_OP
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END"""

INVITATION_FUNCTION = "catalyst_invitation_fixed"
INVITATION_BODY_0005 = """
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
INVITATION_BODY = """
    BEGIN
      IF TG_OP = 'DELETE'
         OR (NEW.id, NEW.public_id, NEW.email_key, NEW.issued_by, NEW.note, NEW.issued_at, NEW.expires_at,
             NEW.notice_template_version, NEW.notice_sha256)
            IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.email_key, OLD.issued_by, OLD.note, OLD.issued_at, OLD.expires_at,
                              OLD.notice_template_version, OLD.notice_sha256)
         OR (OLD.used_at IS NOT NULL AND NEW.used_at IS DISTINCT FROM OLD.used_at)
         OR (OLD.superseded_at IS NOT NULL AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at)
         OR (OLD.application_id IS NOT NULL AND NEW.application_id IS DISTINCT FROM OLD.application_id) THEN
        RAISE EXCEPTION 'invitation: % refused (identity, issuer, expiry and the notice record are fixed; use and supersession are written once)', TG_OP
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


def _replace_function(schema_editor, name, body):
    schema_editor.execute(f"CREATE OR REPLACE FUNCTION public.{name}() RETURNS trigger LANGUAGE plpgsql "
                          f"SET search_path = public, pg_temp AS $$ {body} $$", params=None)
    schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")


def protect(apps, schema_editor):
    _replace_function(schema_editor, FUNCTION, BODY)
    schema_editor.execute(f"CREATE TRIGGER {FUNCTION} BEFORE UPDATE OR DELETE ON public.{TABLE} "
                          f"FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{TABLE} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")
    _replace_function(schema_editor, INVITATION_FUNCTION, INVITATION_BODY)  # the trigger from 0005 stays attached


def unprotect(apps, schema_editor):
    _replace_function(schema_editor, INVITATION_FUNCTION, INVITATION_BODY_0005)
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{TABLE}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {FUNCTION} ON public.{TABLE}")
    schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{FUNCTION}()")


class Migration(migrations.Migration):
    dependencies = [("applications", "0007_notice_record_and_member_on_file")]
    operations = [migrations.RunPython(grant_forward, grant_reverse), migrations.RunPython(backup_sequence, no_backup_sequence),
                  migrations.RunPython(protect, unprotect)]
