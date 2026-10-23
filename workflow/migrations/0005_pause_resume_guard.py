"""9kg.6 (security review of PR #46, HIGH 2; ADR-14 pattern; 016 section 10.14): the automation pause row of an
application is cleared only together with an audited resume. The application role keeps DELETE on
workflow_automationpause (the resume service needs it), so the rule is a deferred constraint trigger, for every role:
a DELETE of a pause is refused at commit unless the same top-level transaction inserted an `automation_resumed`
history event for that application, recorded by staff (actor_type `staff`, a non-empty actor reference); pauses are
keyed by the application's public_ref, events by its id, so the guard joins. A system pause (actor `system` or
`system:...`) also needs a resume note of at least ten characters, which is what the service records
(correspondence.staff_actions.resume). Only the restore hold (`subject_type = 'system'`) is exempt, since it has its
own rule (0004); any other subject type is guarded and, having no application, cannot be cleared at all (fail
closed). An UPDATE of a non-system pause is refused outright (a pause is created and resumed, never changed) and
TRUNCATE by the shared no-truncate function. Stated limitation, as for every ADR-14 guard: the migration owner can
disable the trigger, a superuser bypasses it, and a compromised application role can insert the event itself; the
guard binds code paths and stray writes, not an attacker with the role. Authorization (who may resume) and the
open-cause checks remain in code."""

from django.db import migrations


def protect(apps, schema_editor):
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_pause_resume_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        DECLARE
          system_pause boolean := OLD.actor_ref = 'system' OR OLD.actor_ref LIKE 'system:%';
        BEGIN
          IF OLD.subject_type = 'system' THEN
            RETURN NULL;  -- the restore hold has its own rule (0004); every other subject type is guarded
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM public.applications_applicationevent e
            JOIN public.applications_application a ON a.id = e.application_id
            WHERE a.public_ref = OLD.subject_id
              AND e.kind = 'automation_resumed'
              AND e.created_txid = pg_current_xact_id()::text::bigint  -- inserted in this transaction
              AND e.actor_type = 'staff' AND e.actor_ref <> ''
              AND (NOT system_pause OR length(btrim(coalesce(e.data ->> 'note', ''))) >= 10)
          ) THEN
            IF system_pause THEN
              RAISE EXCEPTION 'automation pause: clearing a system pause needs an automation_resumed event recorded '
                'by staff with an actor reference and a resume note of ten characters or more in the same transaction'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RAISE EXCEPTION 'automation pause: % needs an automation_resumed event for the application, recorded by '
              'staff with an actor reference, in the same transaction', TG_OP USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NULL;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_pause_resume_guard() FROM PUBLIC")
    schema_editor.execute("CREATE CONSTRAINT TRIGGER catalyst_pause_resume_guard AFTER DELETE ON public.workflow_automationpause"
                          " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.catalyst_pause_resume_guard()")
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_pause_fixed() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF OLD.subject_type <> 'system' THEN
            RAISE EXCEPTION 'automation pause: UPDATE refused; a pause is created and resumed, never changed'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_pause_fixed() FROM PUBLIC")
    schema_editor.execute("CREATE TRIGGER catalyst_pause_fixed BEFORE UPDATE ON public.workflow_automationpause"
                          " FOR EACH ROW EXECUTE FUNCTION public.catalyst_pause_fixed()")
    schema_editor.execute("CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.workflow_automationpause"
                          " FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    schema_editor.execute("DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.workflow_automationpause")
    schema_editor.execute("DROP TRIGGER IF EXISTS catalyst_pause_fixed ON public.workflow_automationpause")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_pause_fixed()")
    schema_editor.execute("DROP TRIGGER IF EXISTS catalyst_pause_resume_guard ON public.workflow_automationpause")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_pause_resume_guard()")


class Migration(migrations.Migration):
    dependencies = [("workflow", "0004_restore_hold_protection"), ("applications", "0006_event_txid")]
    operations = [migrations.RunPython(protect, unprotect)]
