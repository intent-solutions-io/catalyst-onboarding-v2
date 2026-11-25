# bgl.24 (D-55): the still-in-review note of a hold.
#
# - The `hold_notice` kind of approved message, frozen by assessments.hold.SendHoldNotice and sent by the P2 sender.
# - The `hold_notice` template, seeded as an unapproved synthetic placeholder (status draft, synthetic), as 0019 seeds the
#   decline notice and 0023 the lapse note: a live environment sends nothing until the owner approves a real version
#   (D-29; the real wording is in correspondence.wording, added as a draft by `catalyst_seed_wording`). Its one variable
#   is the applicant's first name, so no reason, rationale or model output can ever be rendered into it. Nothing is
#   queued for it unless CATALYST_HOLD_NOTICE_ENABLED is on (off by default).
import hashlib

from django.db import migrations, models

KEY = "hold_notice"
SUBJECT = "Your request for access"
BODY = (
    "PLACEHOLDER WORDING, NOT YET APPROVED.\n\n"
    "Hello $first_name,\n\n"
    "This synthetic placeholder says that a request is still in review.\n\n"
    "[owner to state that no action is needed and that we write when there is a decision]\n"
)  # synthetic placeholder wording (POL-17); never approved for real applicants (D-29)
KINDS = [
    "question",
    "reminder",
    "staff_message",
    "welcome",
    "decline",
    "lapse_note",
    "hold_notice",
]


def digest(subject, body):
    return hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()


def create_template(Template, Version):
    """The template and its first draft, unless already present (a re-applied migration keeps any later or approved
    version). Called by this migration and by tests that need the row after the test reset truncated the
    correspondence tables."""
    template, _ = Template.objects.get_or_create(
        key=KEY,
        defaults={
            "secret_bearing": False,
            "purpose": "Tell an applicant on hold, once, that the request is still in review (bgl.24)",
        },
    )
    if not Version.objects.filter(template=template, version=1).exists():
        Version.objects.create(
            template=template,
            version=1,
            subject=SUBJECT,
            body_text=BODY,
            variables=["first_name"],
            secret_bearing=False,
            status="draft",
            content_sha256=digest(SUBJECT, BODY),
            synthetic=True,
        )


def seed(apps, schema_editor):
    create_template(
        apps.get_model("correspondence", "MessageTemplate"),
        apps.get_model("correspondence", "MessageTemplateVersion"),
    )


def unseed(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    # Only the seed this migration made: a later draft or an approved version (frozen, 0015) stays.
    Version.objects.filter(
        template__key=KEY,
        version=1,
        status="draft",
        content_sha256=digest(SUBJECT, BODY),
    ).delete()
    if not Version.objects.filter(template__key=KEY).exists():
        apps.get_model("correspondence", "MessageTemplate").objects.filter(
            key=KEY
        ).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0026_intake_receipt_templates")]
    operations = [
        migrations.RemoveConstraint(
            model_name="approvedmessage", name="approved_message_kind_valid"
        ),
        migrations.AlterField(
            model_name="approvedmessage",
            name="kind",
            field=models.CharField(
                choices=[
                    ("question", "Question"),
                    ("reminder", "Reminder"),
                    ("staff_message", "Staff Message"),
                    ("welcome", "Welcome"),
                    ("decline", "Decline"),
                    ("lapse_note", "Lapse Note"),
                    ("hold_notice", "Hold Notice"),
                ],
                max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name="approvedmessage",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind__in", KINDS)),
                name="approved_message_kind_valid",
            ),
        ),
        migrations.RunPython(seed, unseed),
    ]
