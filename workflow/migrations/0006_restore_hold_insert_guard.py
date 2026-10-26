"""9kg.25 (security review of PR #103, finding 1): the application role may not create a `system` row in
workflow_automationpause either. The restore hold is placed only by `catalyst_restore` (the administrator's load) and,
by hand, by the owner; the erasure replay's database function (`catalyst_erase_replay`, erasure 0004) runs only while
that row exists, so a hold the application role could plant would let the retention login skip the erase function's
refusals on a database in service. 0004 guards UPDATE and DELETE; this adds INSERT. Expand-only; the reverse drops
the trigger and its function."""

from django.conf import settings
from django.db import migrations


def protect(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["app"]])
        app_literal = cursor.fetchone()[0]
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_restore_hold_not_placed() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NEW.subject_type = 'system' AND pg_catalog.pg_has_role(session_user, {app_literal}, 'MEMBER') THEN
            RAISE EXCEPTION 'restore hold: INSERT refused for the application role'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_restore_hold_not_placed() FROM PUBLIC")
    schema_editor.execute("CREATE TRIGGER catalyst_restore_hold_insert BEFORE INSERT ON public.workflow_automationpause"
                          " FOR EACH ROW EXECUTE FUNCTION public.catalyst_restore_hold_not_placed()")


def unprotect(apps, schema_editor):
    schema_editor.execute("DROP TRIGGER IF EXISTS catalyst_restore_hold_insert ON public.workflow_automationpause")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_restore_hold_not_placed()")


class Migration(migrations.Migration):
    dependencies = [("workflow", "0005_pause_resume_guard")]
    operations = [migrations.RunPython(protect, unprotect)]
