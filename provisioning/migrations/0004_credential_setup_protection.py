# P5 5B.2 (023 sections 11.2, 11.5 and 11.7; ADR-14). Runs as the migration owner.
#
# A setup's identity (its request, series and recipient) is fixed at insert. Its token hash is written once and never
# changed; its completion is written once. A terminal state is final: completed, expired, cancelled, superseded and
# invitation_failed never change, and an uncertain series can only be superseded. No setup is ever deleted, and the
# table cannot be truncated. The chosen password is never in this table, or any other.
from django.db import migrations

from config.db_roles import apply_grants

SETUP = "provisioning_credentialsetup"

grant_forward, grant_reverse = apply_grants({
    SETUP: {"app": ["SELECT", "INSERT",
                    "UPDATE (token_sha256, state, expires_at, set_attempts, set_started_at, completed_at, updated_at)"],
            "retention": ["SELECT"]},
})

BODY = """
    BEGIN
      IF TG_OP = 'DELETE'
         OR (NEW.id, NEW.public_id, NEW.request_id, NEW.series, NEW.recipient, NEW.created_at)
            IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.request_id, OLD.series, OLD.recipient, OLD.created_at)
         OR (OLD.token_sha256 <> '' AND NEW.token_sha256 IS DISTINCT FROM OLD.token_sha256)
         OR (OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at)
         OR (OLD.state IN ('completed', 'expired', 'cancelled', 'superseded', 'invitation_failed')
             AND NEW.state IS DISTINCT FROM OLD.state)
         OR (OLD.state IN ('invitation_uncertain', 'set_uncertain') AND NEW.state NOT IN (OLD.state, 'superseded')) THEN
        RAISE EXCEPTION 'credential setup: % refused (identity and token are fixed; a settled series is final)', TG_OP
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END"""


def protect(apps, schema_editor):
    schema_editor.execute("CREATE FUNCTION public.catalyst_credential_setup_fixed() RETURNS trigger LANGUAGE plpgsql "
                          f"SET search_path = public, pg_temp AS $$ {BODY} $$", params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_credential_setup_fixed() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_credential_setup_fixed BEFORE UPDATE OR DELETE ON public.{SETUP} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_credential_setup_fixed()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{SETUP} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{SETUP}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_credential_setup_fixed ON public.{SETUP}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_credential_setup_fixed()")


class Migration(migrations.Migration):
    dependencies = [("provisioning", "0003_credential_setup")]
    operations = [migrations.RunPython(grant_forward, grant_reverse), migrations.RunPython(protect, unprotect)]
