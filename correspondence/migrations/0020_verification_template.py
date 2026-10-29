# 9kg.80: the verification mail as a message template, so the first automated message a real person receives is
# wording the owner approved on the template screen (211.7.7, D-29), with its version and digest recorded, never a code
# constant. Seeded as the unapproved placeholder (status draft, synthetic) with the link as its one variable, so the
# template is secret-bearing (016 3.1): a local or synthetic environment sends the draft with a visible marker, a live
# environment refuses to send it (correspondence.verification) and withholds the request form (applications.views).
import hashlib

from django.db import migrations

KEY = "verification_invitation"
SUBJECT = "Confirm your email address"
BODY = (
    "Hello,\n\n"
    "Someone asked to start an application with this email address. If it was you, open this link to confirm"
    " the address:\n\n$link\n\n"
    "If it was not you, you can ignore this message.\n"
)  # synthetic placeholder wording (POL-17); never approved for real people (D-29)


def digest(subject, body):
    return hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()


def create_template(Template, Version):
    """The template and its first draft. Called by this migration and by tests that need the row after the test
    reset truncated the correspondence tables."""
    template = Template.objects.create(key=KEY, secret_bearing=True,
                                       purpose="The verification mail: the first automated message, with the one-time link")
    Version.objects.create(template=template, version=1, subject=SUBJECT, body_text=BODY, variables=["link"],
                           secret_bearing=True, status="draft", content_sha256=digest(SUBJECT, BODY), synthetic=True)


def seed(apps, schema_editor):
    create_template(apps.get_model("correspondence", "MessageTemplate"), apps.get_model("correspondence", "MessageTemplateVersion"))


def unseed(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    Version.objects.filter(template__key=KEY, status="draft").delete()  # an approved version is frozen (0015)
    if not Version.objects.filter(template__key=KEY).exists():
        apps.get_model("correspondence", "MessageTemplate").objects.filter(key=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0019_decline_notice")]
    operations = [migrations.RunPython(seed, unseed)]
