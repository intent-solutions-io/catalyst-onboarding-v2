# P4 4B.2 (021 sections 4 and 6; ADR-14, D-17). Runs as the migration owner.
#
# 1. Provider observations are protected history: insert-only for the application role, the ADR-14 append-only
#    trigger (with its audited retention path) and the no-truncate trigger. Their transaction marker is always the
#    database's own (the 3B.4 pattern): a supplied value is overwritten.
# 2. Verification is database-visible (decided in 4B.2, closing the limit stated for 4B.1): an instance's
#    `signing_status` becomes `signing_complete_verified` only while it is issued and only when a read observation
#    inserted in the same transaction shows the envelope complete, our identity, exactly our recipients and every
#    required recipient signed, and only from issued (no resurrected cancelled or superseded instance). A verified
#    instance never changes its signing or issue status again (4B.2 security review). This guards code paths and stray writes; a
#    compromised application role could insert such an observation itself (021 section 15).
# 3. The `manage_agreements` permission exists and is assigned to no group (021 section 9).
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

OBSERVATION = "agreements_providerobservation"
INSTANCE = "agreements_agreementinstance"

grant_forward, grant_reverse = apply_grants({
    OBSERVATION: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"]},
})


def protect(apps, schema_editor):
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{OBSERVATION} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_history_append_only()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{OBSERVATION} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_observation_txid() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          NEW.created_txid := pg_current_xact_id()::text::bigint;
          NEW.observed_at := now();
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_agreement_verified_needs_read() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF OLD.signing_status = 'signing_complete_verified'
             AND (NEW.signing_status IS DISTINCT FROM OLD.signing_status OR NEW.issue_status IS DISTINCT FROM OLD.issue_status) THEN
            RAISE EXCEPTION 'agreement instance: a verified signing status never changes'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NEW.signing_status = 'signing_complete_verified' AND OLD.signing_status IS DISTINCT FROM NEW.signing_status
             AND (OLD.issue_status <> 'issued' OR NEW.issue_status <> 'issued' OR NOT EXISTS (
               SELECT 1 FROM public.{OBSERVATION} o
               WHERE o.instance_id = NEW.id AND o.source = 'read' AND o.envelope_status = 'COMPLETED'
                 AND o.identity_match AND o.recipients_match AND o.all_required_signed
                 AND o.created_txid = pg_current_xact_id()::text::bigint)) THEN
            RAISE EXCEPTION 'agreement instance: verified only by a fresh read recorded in the same transaction'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    for name in ("catalyst_observation_txid", "catalyst_agreement_verified_needs_read"):
        schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_observation_txid BEFORE INSERT ON public.{OBSERVATION} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_observation_txid()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_agreement_verified_needs_read BEFORE UPDATE ON public.{INSTANCE} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_agreement_verified_needs_read()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_agreement_verified_needs_read ON public.{INSTANCE}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_observation_txid ON public.{OBSERVATION}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{OBSERVATION}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{OBSERVATION}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_agreement_verified_needs_read()")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_observation_txid()")


def permissions(apps, schema_editor):
    config = apps.get_app_config("agreements")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)  # assigned to no group


class Migration(migrations.Migration):
    dependencies = [("agreements", "0003_provider_observations")]
    operations = [
        migrations.RunPython(permissions, migrations.RunPython.noop),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(protect, unprotect),
    ]
