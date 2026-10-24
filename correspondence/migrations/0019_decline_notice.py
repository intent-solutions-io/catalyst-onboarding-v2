# oc4.11 (029 sections 5.2 and 17.3; 016 section 10.19): the decline notice.
#
# - The `decline` kind of approved message, frozen by `assessments.decline.SendDecline` and sent by the P2 sender.
# - The `decline_notice` template, seeded as an unapproved synthetic placeholder (status draft, synthetic), exactly as
#   0018 seeds the data notice: a local or synthetic environment sends the newest draft with a visible draft marker, a
#   live environment refuses until the owner approves real wording (applications.notices; 211.7.4, 211.7.7). The
#   bracketed slots are what counsel must state; the placeholder makes no promise and no legal claim, and its one
#   variable is the applicant's display name: no reason, rationale or model output can ever be rendered into it.
# - Any `send_decline` action held before this release (created when nothing ran it) is cancelled, never released: it
#   was recorded under a decision that made no choice about the notice, and the handler refuses one anyway.
import hashlib

from django.db import migrations, models

DECLINE_KEY = "decline_notice"
DECLINE_SUBJECT = "Your request for access"
DECLINE_BODY = (
    "PLACEHOLDER WORDING, NOT YET APPROVED.\n\n"
    "Hello $display_name,\n\n"
    "Thank you for your request for access. Your request was reviewed, and access is not being offered at this "
    "time.\n\n"
    "[counsel to state whether a reason may be requested, and how]\n"
    "[counsel to state whether and when a new request may be made]\n"
    "[counsel to state what is kept about the request, for how long, and how to request erasure]\n\n"
    "[counsel to state whether replies to this message are read]\n"
)  # synthetic placeholder wording; never approved for real applicants (D-29)


def digest(subject, body):
    return hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()


def create_template(Template, Version):
    """The template and its first draft. Called by this migration and, because the test reset truncates every
    correspondence table, by the tests that need it (tests/test_decline_notice.py)."""
    template = Template.objects.create(key=DECLINE_KEY, secret_bearing=False,
                                       purpose="Tell a declined applicant the outcome; no reason or rationale (oc4.11)")
    Version.objects.create(template=template, version=1, subject=DECLINE_SUBJECT, body_text=DECLINE_BODY,
                           variables=["display_name"], secret_bearing=False, status="draft",
                           content_sha256=digest(DECLINE_SUBJECT, DECLINE_BODY), synthetic=True)


def seed(apps, schema_editor):
    create_template(apps.get_model("correspondence", "MessageTemplate"),
                    apps.get_model("correspondence", "MessageTemplateVersion"))


def unseed(apps, schema_editor):
    apps.get_model("correspondence", "MessageTemplateVersion").objects.filter(template__key=DECLINE_KEY, status="draft").delete()
    apps.get_model("correspondence", "MessageTemplate").objects.filter(key=DECLINE_KEY, versions__isnull=True).delete()


def cancel_held(apps, schema_editor):
    from django.db.models.functions import Now

    apps.get_model("workflow", "PendingAction").objects.filter(kind="send_decline", status="held").update(
        status="cancelled", last_error="held_before_the_decline_handler", completed_at=Now(), updated_at=Now())


def uncancel_held(apps, schema_editor):
    """Reverse of `cancel_held`: only the rows it cancelled (their `last_error` marker) go back to held."""
    from django.db.models.functions import Now

    apps.get_model("workflow", "PendingAction").objects.filter(
        kind="send_decline", status="cancelled", last_error="held_before_the_decline_handler").update(
        status="held", last_error="", completed_at=None, updated_at=Now())


class Migration(migrations.Migration):
    # The pending-action table is reached through 0003's dependency on workflow; no later workflow migration is needed.
    dependencies = [("correspondence", "0018_intake_notice_templates")]
    operations = [
        migrations.RemoveConstraint(model_name="approvedmessage", name="approved_message_kind_valid"),
        migrations.AlterField(
            model_name="approvedmessage", name="kind",
            field=models.CharField(choices=[("question", "Question"), ("reminder", "Reminder"),
                                            ("staff_message", "Staff Message"), ("welcome", "Welcome"),
                                            ("decline", "Decline")], max_length=24),
        ),
        migrations.AddConstraint(
            model_name="approvedmessage",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind__in", ["question", "reminder", "staff_message", "welcome", "decline"])),
                name="approved_message_kind_valid"),
        ),
        migrations.RunPython(seed, unseed),
        migrations.RunPython(cancel_held, uncancel_held),
    ]
