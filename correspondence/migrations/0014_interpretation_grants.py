# P3 3B.3 (018 5.4; 3B.3). Runs as the migration owner.
#
# Reply interpretations are inserted before the model call and finished once: the application role may update
# only the result columns. The new question columns (criterion, gap, route, source, round, text key) need no
# grant change: they are written at insert and the existing UPDATE grant does not include them, so they never
# change afterwards.
#
# A finished interpretation is frozen: the `catalyst_interpretation_result_once` trigger refuses any UPDATE of a row
# whose status is no longer `started`, for every role (the pattern of `catalyst_run_result_once`).
from django.db import migrations

from config.db_roles import apply_grants

forward_grants, reverse_grants = apply_grants({
    "correspondence_replyinterpretation": {
        "app": ["SELECT", "INSERT", "UPDATE (status, code, proposals, problems, flags, provenance, finished_at)"],
        "retention": ["SELECT"],
    },
})


TABLE = "correspondence_replyinterpretation"


def protect(apps, schema_editor):
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_interpretation_result_once() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF OLD.status <> 'started' THEN
            RAISE EXCEPTION 'interpretation result is written once: % on a % row refused', TG_OP, OLD.status
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_interpretation_result_once() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_interpretation_result_once BEFORE UPDATE ON public.{TABLE} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_interpretation_result_once()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_interpretation_result_once ON public.{TABLE}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_interpretation_result_once()")


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0013_clarification_and_interpretation")]
    operations = [migrations.RunPython(forward_grants, reverse_grants), migrations.RunPython(protect, unprotect)]
