# Least-privilege grants for the P2 outbound tables (016 section 3; ADR-14, D-17; owner decision D-28), the
# P2 role groups (016 F, D-30) and the synthetic question template (D-29). Runs as the migration owner.
#
# Identity and content columns are INSERT-only for the application role; only the named status columns
# are updatable; no role may delete any of these rows. StaffItemResolution is INSERT-only (immutable).
# The question template is seeded as a synthetic draft: the owner approves it through the service.
import hashlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants, grant, revoke_all

# Frozen copy of correspondence.roles at this migration (later tasks add permissions in their own migrations).
GROUP_PERMISSIONS = {
    "Correspondence operator": ["approve_question"],
    "Correspondence decision-maker": ["approve_question", "decide_uncertain_send"],
    "Template owner": ["approve_template_version"],
}

OUTBOUND_S1 = ["SELECT", "INSERT", "UPDATE (status, message_id, sent_at)"]
OUTBOUND_P2 = ["SELECT", "INSERT",
               "UPDATE (status, message_id, sent_at, protocol_phase_reached, smtp_reply_code, server_accepted_at)"]

forward_grants, reverse_grants = apply_grants({
    "correspondence_messagetemplate": {"app": ["SELECT", "INSERT"]},
    "correspondence_messagetemplateversion": {"app": ["SELECT", "INSERT", "UPDATE (status, approved_by, approved_at)"]},
    "correspondence_question": {"app": [
        "SELECT", "INSERT",
        "UPDATE (status, approval_state, approved_by, approved_at, withdrawn_by, withdrawn_reason, withdrawn_at, updated_at)",
    ]},
    "correspondence_approvedmessage": {"app": ["SELECT", "INSERT", "UPDATE (disposition, disposition_at, disposition_by)"]},
    "correspondence_approvedmessagequestion": {"app": ["SELECT", "INSERT"]},
    "correspondence_staffitem": {"app": ["SELECT", "INSERT", "UPDATE (status)"]},
    "correspondence_staffitemresolution": {"app": ["SELECT", "INSERT"]},
})


def outbound_forward(apps, schema_editor):
    revoke_all(schema_editor, "correspondence_outboundmessage", "app")
    grant(schema_editor, "correspondence_outboundmessage", "app", OUTBOUND_P2)


def outbound_reverse(apps, schema_editor):
    revoke_all(schema_editor, "correspondence_outboundmessage", "app")
    grant(schema_editor, "correspondence_outboundmessage", "app", OUTBOUND_S1)


def create_groups(apps, schema_editor):
    config = apps.get_app_config("correspondence")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set([Permission.objects.get(content_type__app_label="correspondence", codename=c) for c in codenames])


def delete_groups(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=list(GROUP_PERMISSIONS)).delete()


QUESTION_SUBJECT = "A question about your application"
QUESTION_BODY = (
    "Hello $display_name,\n\n"
    "We have a question about your application:\n\n"
    "$question_text\n\n"
    "Please reply to this message.\n"
)  # synthetic placeholder wording (POL-17); never approved for real applicants (D-29)


def seed_question_template(apps, schema_editor):
    Template = apps.get_model("correspondence", "MessageTemplate")
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    template = Template.objects.create(key="question_request", purpose="Ask an applicant an approved question",
                                       secret_bearing=False)
    digest = hashlib.sha256(f"{QUESTION_SUBJECT}\n{QUESTION_BODY}".encode()).hexdigest()
    Version.objects.create(template=template, version=1, subject=QUESTION_SUBJECT, body_text=QUESTION_BODY,
                           variables=["display_name", "question_text"], secret_bearing=False, status="draft",
                           content_sha256=digest, synthetic=True)


def unseed_question_template(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    Template = apps.get_model("correspondence", "MessageTemplate")
    Version.objects.filter(template__key="question_request").delete()
    Template.objects.filter(key="question_request").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("correspondence", "0003_outbound_foundations"),
        ("accounts", "0003_staff_view"),
    ]
    operations = [
        migrations.RunPython(forward_grants, reverse_grants),
        migrations.RunPython(outbound_forward, outbound_reverse),
        migrations.RunPython(create_groups, delete_groups),
        migrations.RunPython(seed_question_template, unseed_question_template),
    ]
