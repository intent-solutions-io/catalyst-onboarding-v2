# P3 3B.4 (018 section 7; ADR-14, D-17, D-34). Runs as the migration owner.
#
# 1. Decisions are insert-only for the application role and protected history: the ADR-14 append-only trigger
#    (with its audited retention path) and the no-truncate trigger, reusing the functions applications 0002 created.
# 2. The database backstop (TEST-P3-52): web and worker share the application role, which may update `stage`, so a
#    deferred constraint trigger refuses, for every role, any move into `admitted`, `declined` or `on_hold` unless
#    a decision row with the matching outcome was inserted in the same transaction. "Same transaction" is the row's
#    `created_txid` (its database default, the top-level transaction id) equal to the current one: unlike `xmin`,
#    it holds when the row was inserted inside a savepoint.
# 3. The decision permission exists (0007) but is assigned to no group: it is granted to named people only, and
#    `decisions.can_decide` ignores group grants.
# The backstop guards code paths and stray writes; it does not stop a compromised application role, which may
# insert a decision row itself (stated in 018 section 17).
from django.db import migrations

from config.db_roles import apply_grants

DECISION = "assessments_qualificationdecision"

grant_forward, grant_reverse = apply_grants({
    DECISION: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"]},
})


def protect(apps, schema_editor):
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{DECISION} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_history_append_only()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{DECISION} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_decided_stage_needs_decision() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NEW.stage IN ('admitted', 'declined', 'on_hold')
             AND (TG_OP = 'INSERT' OR NEW.stage IS DISTINCT FROM OLD.stage) THEN
            IF NOT EXISTS (
              SELECT 1 FROM public.{DECISION} d
              WHERE d.application_id = NEW.id
                AND d.outcome = CASE NEW.stage WHEN 'admitted' THEN 'admit' WHEN 'declined' THEN 'decline' ELSE 'hold' END
                AND d.created_txid = pg_current_xact_id()::text::bigint  -- inserted in this transaction
            ) THEN
              RAISE EXCEPTION 'stage % needs a qualification decision recorded in the same transaction', NEW.stage
                USING ERRCODE = 'insufficient_privilege';
            END IF;
          END IF;
          RETURN NULL;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_decided_stage_needs_decision() FROM PUBLIC")
    # The transaction marker is always the database's own: a supplied value is overwritten (3B.4 review). Django
    # names db_default columns in its INSERT, so a column-level grant cannot do this.
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_decision_txid() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          NEW.created_txid := pg_current_xact_id()::text::bigint;
          NEW.created_at := now();
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_decision_txid() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_decision_txid BEFORE INSERT ON public.{DECISION} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_decision_txid()")
    schema_editor.execute("CREATE CONSTRAINT TRIGGER catalyst_decided_stage_needs_decision "
                          "AFTER INSERT OR UPDATE OF stage ON public.applications_application "
                          "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                          "EXECUTE FUNCTION public.catalyst_decided_stage_needs_decision()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_decision_txid ON public.{DECISION}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_decision_txid()")
    schema_editor.execute("DROP TRIGGER IF EXISTS catalyst_decided_stage_needs_decision ON public.applications_application")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_decided_stage_needs_decision()")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{DECISION}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{DECISION}")


class Migration(migrations.Migration):
    dependencies = [("assessments", "0007_qualification_decision")]
    operations = [migrations.RunPython(grant_forward, grant_reverse), migrations.RunPython(protect, unprotect)]
