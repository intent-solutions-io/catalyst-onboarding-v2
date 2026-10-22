"""6B.7a (026 section 6; PR #67 review): the restore hold is a `system` row in workflow_automationpause. The
application role may still create and remove an application's pause (P2), but it may never change or remove a
`system` row: only the post-restore step, run as the owner, lifts the hold."""

from django.conf import settings
from django.db import migrations


def protect(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["app"]])
        app_literal = cursor.fetchone()[0]
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_restore_hold_fixed() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF OLD.subject_type = 'system' AND pg_catalog.pg_has_role(session_user, {app_literal}, 'MEMBER') THEN
            RAISE EXCEPTION 'restore hold: % refused for the application role', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_restore_hold_fixed() FROM PUBLIC")
    schema_editor.execute("CREATE TRIGGER catalyst_restore_hold BEFORE UPDATE OR DELETE ON public.workflow_automationpause"
                          " FOR EACH ROW EXECUTE FUNCTION public.catalyst_restore_hold_fixed()")


def unprotect(apps, schema_editor):
    schema_editor.execute("DROP TRIGGER IF EXISTS catalyst_restore_hold ON public.workflow_automationpause")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_restore_hold_fixed()")


class Migration(migrations.Migration):
    dependencies = [("workflow", "0003_backup_role_reads")]
    operations = [migrations.RunPython(protect, unprotect)]
