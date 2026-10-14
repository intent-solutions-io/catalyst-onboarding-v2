# P3 3B.2 (018 5.1, 6; ADR-14). Runs as the migration owner.
#
# 1. Grants: a run's identity, snapshot and pack columns are INSERT-only; only its status and result columns are
#    updatable. Invocations update only their status and end time.
# 2. A run's result is written once: the `catalyst_run_result_once` trigger refuses any UPDATE of a finished run
#    (status other than queued or reserved), for every role.
# 3. Assessment operators may request a rerun (a new snapshot only).
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

RUN = "assessments_assessmentrun"
RESULT = ("status, error_code, output, output_sha256, validation_codes, flags, requests_used, input_tokens, "
          "output_tokens, finished_at, request_sha256, provider, model_id, output_mode, library_version")

grant_forward, grant_reverse = apply_grants({
    RUN: {"app": ["SELECT", "INSERT", f"UPDATE ({RESULT})"], "retention": ["SELECT"]},
    "assessments_assessmentinvocation": {"app": ["SELECT", "INSERT", "UPDATE (status, finished_at, used_tokens)"]},
})


def protect(apps, schema_editor):
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_run_result_once() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF OLD.status NOT IN ('queued', 'reserved') THEN
            RAISE EXCEPTION 'run result is written once: % on a % run refused', TG_OP, OLD.status
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_run_result_once() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_run_result_once BEFORE UPDATE ON public.{schema_editor.quote_name(RUN)} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_run_result_once()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_run_result_once ON public.{schema_editor.quote_name(RUN)}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_run_result_once()")


def add_permission(apps, schema_editor):
    config = apps.get_app_config("assessments")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    group, _ = apps.get_model("auth", "Group").objects.get_or_create(name="Assessment operator")
    group.permissions.add(*apps.get_model("auth", "Permission").objects.filter(
        content_type__app_label="assessments", codename="rerun_assessment"))


def remove_permission(apps, schema_editor):
    group = apps.get_model("auth", "Group").objects.filter(name="Assessment operator").first()
    if group is not None:
        group.permissions.remove(*apps.get_model("auth", "Permission").objects.filter(
            content_type__app_label="assessments", codename="rerun_assessment"))


class Migration(migrations.Migration):
    dependencies = [("assessments", "0004_assessment_runs")]
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(protect, unprotect),
        migrations.RunPython(add_permission, remove_permission),
    ]
