# P4 4B.3 (021 sections 7 and 8; ADR-14). Runs as the migration owner.
#
# 1. Stored documents and document accesses are history: insert-only for the application role, and the strict
#    append-only and no-truncate triggers for every role (a retention path is a POL-10 decision, not built).
# 2. Required-details versions: inserted as drafts; only the confirmation columns change, once, from draft to
#    confirmed; values never change and a version is never deleted (catalyst_agreement_details_frozen).
# 3. The new permissions exist and are assigned to no group (021 section 9).
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

DOCUMENT = "agreements_storeddocument"
ACCESS = "agreements_documentaccess"
DETAILS = "agreements_agreementdetailsversion"

grant_forward, grant_reverse = apply_grants({
    DOCUMENT: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"]},
    ACCESS: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"]},
    DETAILS: {"app": ["SELECT", "INSERT", "UPDATE (status, confirmed_by, confirmed_at)"], "retention": ["SELECT"]},
})


def protect(apps, schema_editor):
    for table in (DOCUMENT, ACCESS):
        schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{table} "
                              "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
        schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{table} "
                              "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_agreement_details_frozen() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.status <> 'draft' OR NEW.confirmed_by <> '' OR NEW.confirmed_at IS NOT NULL THEN
              RAISE EXCEPTION 'agreement details: a version is recorded as a draft first'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE' AND NEW.status = 'confirmed' AND (NEW.confirmed_by = '' OR NEW.confirmed_at IS NULL) THEN
            RAISE EXCEPTION 'agreement details: a confirmation names who and when'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF TG_OP = 'DELETE' OR OLD.status <> 'draft'
             OR (NEW.application_id, NEW.agreement_type_id, NEW.version, NEW.values::text, NEW.values_sha256,
                 NEW.recorded_by, NEW.created_at, NEW.public_id)
                IS DISTINCT FROM
                (OLD.application_id, OLD.agreement_type_id, OLD.version, OLD.values::text, OLD.values_sha256,
                 OLD.recorded_by, OLD.created_at, OLD.public_id) THEN
            RAISE EXCEPTION 'agreement details: % refused (values are fixed; a confirmed version is final)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_agreement_details_frozen() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_agreement_details_frozen BEFORE INSERT OR UPDATE OR DELETE "
                          f"ON public.{DETAILS} FOR EACH ROW EXECUTE FUNCTION public.catalyst_agreement_details_frozen()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{DETAILS} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{DETAILS}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_agreement_details_frozen ON public.{DETAILS}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_agreement_details_frozen()")
    for table in (DOCUMENT, ACCESS):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{table}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{table}")


def permissions(apps, schema_editor):
    config = apps.get_app_config("agreements")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)  # assigned to no group


class Migration(migrations.Migration):
    dependencies = [("agreements", "0007_custody_and_details")]
    operations = [
        migrations.RunPython(permissions, migrations.RunPython.noop),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(protect, unprotect),
    ]
