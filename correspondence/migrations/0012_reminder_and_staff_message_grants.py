# P2 2B.4 (016 E, F, 3.3, 3.4; owner decisions D-28 A-5, A-8, D-30). Runs as the migration owner.
#
# 1. Staff-message drafts are INSERT-only for the application role (a preview is never edited; 3.4).
# 2. The role matrix gains the 2B.4 staff controls for operators and decision-makers: withdraw_question,
#    send_staff_message, pause_automation and resume_automation (frozen literal map).
# 3. A synthetic draft `question_reminder` template (version 1). It sends nothing until the owner approves
#    it (D-29); production wording needs POL-06 and POL-17.
import hashlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

forward_grants, reverse_grants = apply_grants({
    "correspondence_staffmessagedraft": {"app": ["SELECT", "INSERT"]},
})

CONTROLS = ["withdraw_question", "send_staff_message", "pause_automation", "resume_automation"]
ADDED = {"Correspondence operator": CONTROLS, "Correspondence decision-maker": CONTROLS}

REMINDER_SUBJECT = "A reminder about your application"
REMINDER_BODY = ("Hello $display_name,\n\nWe are still waiting for your answer to this question:\n\n$question_text\n\n"
                 "Please reply to this message.\n")


def add_permissions(apps, schema_editor):
    config = apps.get_app_config("correspondence")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in ADDED.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.add(*Permission.objects.filter(content_type__app_label="correspondence", codename__in=codenames))


def remove_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in ADDED.items():
        group = Group.objects.filter(name=name).first()
        if group is not None:
            group.permissions.remove(*Permission.objects.filter(content_type__app_label="correspondence", codename__in=codenames))


def seed_reminder_template(apps, schema_editor):
    Template = apps.get_model("correspondence", "MessageTemplate")
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    template, _ = Template.objects.get_or_create(key="question_reminder", defaults={
        "purpose": "Remind an applicant of an unanswered approved question", "secret_bearing": False})
    if not Version.objects.filter(template=template, version=1).exists():
        digest = hashlib.sha256(f"{REMINDER_SUBJECT}\n{REMINDER_BODY}".encode()).hexdigest()
        Version.objects.create(template=template, version=1, subject=REMINDER_SUBJECT, body_text=REMINDER_BODY,
                               variables=["display_name", "question_text"], secret_bearing=False, status="draft",
                               content_sha256=digest, synthetic=True)


def unseed_reminder_template(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    Template = apps.get_model("correspondence", "MessageTemplate")
    Version.objects.filter(template__key="question_reminder", status="draft").delete()
    Template.objects.filter(key="question_reminder", versions__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0011_reminders_and_staff_messages")]
    operations = [
        migrations.RunPython(forward_grants, reverse_grants),
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(seed_reminder_template, unseed_reminder_template),
    ]
