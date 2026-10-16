# P3 3B.3 (018 step 6): assessment operators may author clarification questions. Approving and sending them stays
# with the correspondence operators (D-29). Runs as the migration owner.
from django.contrib.auth.management import create_permissions
from django.db import migrations


def add(apps, schema_editor):
    config = apps.get_app_config("correspondence")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    group, _ = apps.get_model("auth", "Group").objects.get_or_create(name="Assessment operator")
    group.permissions.add(*apps.get_model("auth", "Permission").objects.filter(
        content_type__app_label="correspondence", codename="author_question"))


def remove(apps, schema_editor):
    group = apps.get_model("auth", "Group").objects.filter(name="Assessment operator").first()
    if group is not None:
        group.permissions.remove(*apps.get_model("auth", "Permission").objects.filter(
            content_type__app_label="correspondence", codename="author_question"))


class Migration(migrations.Migration):
    dependencies = [("assessments", "0005_assessment_grants_and_protection"),
                    ("correspondence", "0014_interpretation_grants")]
    operations = [migrations.RunPython(add, remove)]
