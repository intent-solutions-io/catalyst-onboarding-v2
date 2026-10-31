# bgl.7 (034 row 21): the lapse's closing note.
#
# - The `lapse_note` kind of approved message, frozen by correspondence.lapse.Lapse and sent by the P2 sender.
# - The `lapse_note` template, seeded as an unapproved synthetic placeholder (status draft, synthetic), as 0012 seeds the
#   reminder: it sends nothing until the owner approves a version (D-29). Until then a due lapse waits with one
#   `lapse_note_refused` staff item. The bracketed slots are what the owner must state; the placeholder promises nothing
#   and sets no deadline (a lapse is not a decision), and its one variable is the applicant's display name.
import hashlib

from django.db import migrations, models

KEY = "lapse_note"
SUBJECT = "Your application"
BODY = (
    "PLACEHOLDER WORDING, NOT YET APPROVED.\n\n"
    "Hello $display_name,\n\n"
    "We have not heard back from you, so we are setting your application aside for now.\n\n"
    "[owner to state that the application is kept on file and how to pick it up again: a reply to this message]\n"
    "[owner to state that there is no deadline and nothing further is expected]\n"
)  # synthetic placeholder wording (POL-17); never approved for real applicants (D-29)
KINDS = ["question", "reminder", "staff_message", "welcome", "decline", "lapse_note"]


def digest(subject, body):
    return hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()


def create_template(Template, Version):
    """The template and its first draft, unless already present (a re-applied migration keeps any later or approved
    version). Called by this migration and by tests that need the row after the test reset truncated the
    correspondence tables."""
    template, _ = Template.objects.get_or_create(
        key=KEY, defaults={"secret_bearing": False,
                           "purpose": "Tell an applicant who stayed quiet that the application is set aside, not closed (bgl.7)"})
    if not Version.objects.filter(template=template, version=1).exists():
        Version.objects.create(template=template, version=1, subject=SUBJECT, body_text=BODY, variables=["display_name"],
                               secret_bearing=False, status="draft", content_sha256=digest(SUBJECT, BODY), synthetic=True)


def seed(apps, schema_editor):
    create_template(apps.get_model("correspondence", "MessageTemplate"), apps.get_model("correspondence", "MessageTemplateVersion"))


def unseed(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    # Only the seed this migration made: a later draft or an approved version (frozen, 0015) stays.
    Version.objects.filter(template__key=KEY, version=1, status="draft", content_sha256=digest(SUBJECT, BODY)).delete()
    if not Version.objects.filter(template__key=KEY).exists():
        apps.get_model("correspondence", "MessageTemplate").objects.filter(key=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0020_verification_template")]
    operations = [
        migrations.RemoveConstraint(model_name="approvedmessage", name="approved_message_kind_valid"),
        migrations.AlterField(
            model_name="approvedmessage", name="kind",
            field=models.CharField(choices=[("question", "Question"), ("reminder", "Reminder"),
                                            ("staff_message", "Staff Message"), ("welcome", "Welcome"),
                                            ("decline", "Decline"), ("lapse_note", "Lapse Note")], max_length=24),
        ),
        migrations.AddConstraint(
            model_name="approvedmessage",
            constraint=models.CheckConstraint(condition=models.Q(("kind__in", KINDS)), name="approved_message_kind_valid"),
        ),
        migrations.RunPython(seed, unseed),
    ]
