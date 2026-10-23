"""9kg.6 (security review of PR #46, HIGH 2; ADR-14 pattern; 016 section 10.13): the automation pause row of an
application is cleared only by an audited resume. The application role keeps DELETE on workflow_automationpause (the
resume service needs it), so the rule is a deferred constraint trigger, for every role: a DELETE of an application's
pause is refused at commit unless the same top-level transaction inserted an `automation_resumed` history event for
that application (pauses are keyed by the application's public_ref, events by its id, so the guard joins). A system
pause (actor `system` or `system:...`) also needs that event recorded by staff, with a non-empty actor reference and a
resume note, which is what the service records (correspondence.staff_actions.resume). An UPDATE of an application's
pause is refused outright (a pause is created and resumed, never changed) and TRUNCATE is refused by the shared
no-truncate function. The restore hold (`system` rows) keeps its own rule (0004). Stated limitation, as for every
ADR-14 guard: the migration owner can disable the trigger, a superuser bypasses it, and a compromised application role
can insert the event itself; the guard binds code paths and stray writes, not an attacker with the role."""

from django.db import migrations


def protect(apps, schema_editor):
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_pause_resume_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        DECLARE
          system_pause boolean := OLD.actor_ref = 'system' OR OLD.actor_ref LIKE 'system:%';
        BEGIN
          IF OLD.subject_type <> 'application' THEN
            RETURN NULL;  -- the restore hold has its own rule (0004)
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM public.applications_applicationevent e
            JOIN public.applications_application a ON a.id = e.application_id
            WHERE a.public_ref = OLD.subject_id
              AND e.kind = 'automation_resumed'
              AND e.created_txid = pg_current_xact_id()::text::bigint  -- inserted in this transaction
              AND (NOT system_pause OR (e.actor_type = 'staff' AND e.actor_ref <> ''
                                        AND coalesce(e.data ->> 'note', '') <> ''))
          ) THEN
            IF system_pause THEN
              RAISE EXCEPTION 'automation pause: clearing a system pause needs an automation_resumed event recorded '
                'by staff with an actor reference and a resume note in the same transaction'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RAISE EXCEPTION 'automation pause: % needs an automation_resumed event for the application in the same '
              'transaction', TG_OP USING ERRCODE = 'insufficient_privilege';
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
          IF OLD.subject_type = 'application' THEN
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
