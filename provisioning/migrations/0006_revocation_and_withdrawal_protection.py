# P5 5B.3 (023 sections 6 and 11.6; ADR-14). Runs as the migration owner.
#
# An access revocation's identity (its request and kind) is fixed; a verified, not-applicable or exception outcome is
# final, and an exception names who decided it. A withdrawal confirmation's identity and recipient are fixed, its token
# hash is written once, and a used, expired or superseded confirmation is final. No row is ever deleted, and neither
# table can be truncated. The new permission `close_application` is assigned to no group.
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

REVOCATION = "provisioning_accessrevocation"
WITHDRAWAL = "provisioning_withdrawalconfirmation"

grant_forward, grant_reverse = apply_grants({
    REVOCATION: {"app": ["SELECT", "INSERT", "UPDATE (state, note, decided_by, updated_at)"], "retention": ["SELECT"]},
    WITHDRAWAL: {"app": ["SELECT", "INSERT", "UPDATE (token_sha256, state, expires_at, updated_at)"],
                 "retention": ["SELECT"]},
})

FUNCTIONS = {
    "catalyst_access_revocation_fixed": """
        BEGIN
          IF TG_OP = 'DELETE'
             OR (NEW.id, NEW.public_id, NEW.request_id, NEW.kind, NEW.created_at)
                IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.request_id, OLD.kind, OLD.created_at)
             OR (OLD.state IN ('verified', 'not_applicable', 'exception') AND NEW.state IS DISTINCT FROM OLD.state)
             OR (OLD.decided_by <> '' AND NEW.decided_by IS DISTINCT FROM OLD.decided_by) THEN
            RAISE EXCEPTION 'access revocation: % refused (identity is fixed; a settled obligation is final)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END""",
    "catalyst_withdrawal_confirmation_fixed": """
        BEGIN
          IF TG_OP = 'DELETE'
             OR (NEW.id, NEW.public_id, NEW.application_id, NEW.recipient, NEW.requested_by, NEW.created_at)
                IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.application_id, OLD.recipient, OLD.requested_by, OLD.created_at)
             OR (OLD.token_sha256 <> '' AND NEW.token_sha256 IS DISTINCT FROM OLD.token_sha256)
             OR (OLD.state IN ('used', 'expired', 'superseded') AND NEW.state IS DISTINCT FROM OLD.state) THEN
            RAISE EXCEPTION 'withdrawal confirmation: % refused (identity and token are fixed; a settled one is final)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END""",
}
TABLES = {"catalyst_access_revocation_fixed": REVOCATION, "catalyst_withdrawal_confirmation_fixed": WITHDRAWAL}


def protect(apps, schema_editor):
    for name, body in FUNCTIONS.items():
        schema_editor.execute(f"CREATE FUNCTION public.{name}() RETURNS trigger LANGUAGE plpgsql "
                              f"SET search_path = public, pg_temp AS $$ {body} $$", params=None)
        schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")
        schema_editor.execute(f"CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON public.{TABLES[name]} "
                              f"FOR EACH ROW EXECUTE FUNCTION public.{name}()")
    for table in (REVOCATION, WITHDRAWAL):
        schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{table} "
                              "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    for table in (REVOCATION, WITHDRAWAL):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{table}")
    for name, table in TABLES.items():
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name} ON public.{table}")
        schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{name}()")


def permissions(apps, schema_editor):
    config = apps.get_app_config("provisioning")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)  # assigned to no group


class Migration(migrations.Migration):
    dependencies = [("provisioning", "0005_revocation_and_withdrawal")]
    operations = [migrations.RunPython(grant_forward, grant_reverse), migrations.RunPython(protect, unprotect),
                  migrations.RunPython(permissions, migrations.RunPython.noop)]
