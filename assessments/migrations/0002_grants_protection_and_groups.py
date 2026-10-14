# P3 3B.1 (018 sections 3.1, 3.2, 7; ADR-14, D-17, D-34; P3-D-14). Runs as the migration owner.
#
# 1. Least-privilege grants: sources are INSERT-only except their approval columns (an approved version is never
#    edited; a change is a new version); items update only their status columns; captures are INSERT-only.
# 2. Captures are protected history: the ADR-14 append-only trigger (with its audited retention path) and the
#    no-truncate trigger, reusing the functions applications 0002 created.
# 3. Permissions and two groups: "Assessment operator" (read evidence, re-fetch, proceed without) and
#    "Evidence source owner" (approve source versions). No decision permission exists yet (3B.4).
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

CAPTURE = "assessments_evidencecapture"

grant_forward, grant_reverse = apply_grants({
    "assessments_evidencesource": {"app": ["SELECT", "INSERT", "UPDATE (status, approved_by, approved_at)"]},
    "assessments_evidenceitem": {"app": ["SELECT", "INSERT", "UPDATE (status, reason_code, finished_at, updated_at)"]},
    CAPTURE: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"]},
})


def protect(apps, schema_editor):
    q = schema_editor.quote_name(CAPTURE)
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{q} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_history_append_only()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{q} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    q = schema_editor.quote_name(CAPTURE)
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{q}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{q}")


GROUPS = {
    "Assessment operator": ["review_evidence", "operate_evidence"],
    "Evidence source owner": ["approve_evidence_source"],
}


def add_groups(apps, schema_editor):
    config = apps.get_app_config("assessments")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.add(*Permission.objects.filter(content_type__app_label="assessments", codename__in=codenames))


def remove_groups(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=list(GROUPS)).delete()


class Migration(migrations.Migration):
    dependencies = [("assessments", "0001_initial"), ("applications", "0003_protect_version_adoption"),
                    ("correspondence", "0012_reminder_and_staff_message_grants")]
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(protect, unprotect),
        migrations.RunPython(add_groups, remove_groups),
    ]
