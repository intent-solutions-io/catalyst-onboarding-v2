# bgl.5 (034 rows 7 and 9, section 1.2 steps 1 and 2): the receipt an applicant gets at the first submission, as message
# templates, so its wording is approved by the owner on the template screen (D-29) and reaches production through the
# wording loader (bgl.11), never through this repository. Two keys, because a template's variables are an exact
# allow-list (016 A1):
#
# - `intake_receipt`: the receipt alone, sent as its own mail before the confirm-your-address mail
#   (CATALYST_INTAKE_RECEIPT on, CATALYST_RECEIPT_IS_VERIFICATION off);
# - `intake_receipt_confirm`: the receipt that is also the verification mail, carrying the one-time link
#   (CATALYST_RECEIPT_IS_VERIFICATION on), so secret-bearing (016 3.1).
#
# Both subjects are static and ask the sender to append the application's reference (`subject_reference`, migration
# 0021). Seeded as unapproved, synthetic placeholders: a local or synthetic environment sends a draft with its marker; a
# live environment sends nothing and withholds intake until the owner approves real wording (applications.notices).
import hashlib

from django.db import migrations

RECEIPT_KEY = "intake_receipt"
CONFIRM_KEY = "intake_receipt_confirm"
VARIABLES = ["greeting", "reference", "submitted_on", "interest"]
SUBJECT = "Your request was received"
BODY = (
    "$greeting,\n\n"
    "This synthetic placeholder confirms that a request arrived.\n\n"
    "Reference: $reference\n"
    "Submitted: $submitted_on\n"
    "Interest: $interest\n\n"
    "Placeholder text: replies go to this address.\n"
)  # synthetic placeholder wording (POL-17); never approved for real people (D-29)
CONFIRM_BODY = (
    "$greeting,\n\n"
    "This synthetic placeholder confirms that a request arrived.\n\n"
    "Reference: $reference\n"
    "Submitted: $submitted_on\n"
    "Interest: $interest\n\n"
    "Placeholder text: open this link to confirm the address:\n\n$link\n\n"
    "Placeholder text: if it was not you, ignore this message.\n"
)  # synthetic placeholder wording (POL-17); never approved for real people (D-29)
SEEDS = {
    RECEIPT_KEY: (SUBJECT, BODY, VARIABLES, False,
                  "The receipt at the first submission, with the reference (bgl.5)"),
    CONFIRM_KEY: (SUBJECT, CONFIRM_BODY, [*VARIABLES, "link"], True,
                  "The receipt that is also the verification mail, with the reference and the one-time link (bgl.5)"),
}


def digest(subject, body):
    """The version digest with the reference flag on (correspondence.rendering.version_digest), frozen here."""
    return hashlib.sha256(f"{subject} [$reference]\n{body}".encode()).hexdigest()


def create_templates(Template, Version):
    """Each template and its first draft, unless already present (a re-applied migration keeps any later or approved
    version). Called by this migration and by tests that need the rows after the test reset truncated the tables."""
    for key, (subject, body, variables, secret_bearing, purpose) in SEEDS.items():
        template, _ = Template.objects.get_or_create(key=key, defaults={"secret_bearing": secret_bearing, "purpose": purpose})
        if not Version.objects.filter(template=template, version=1).exists():
            Version.objects.create(template=template, version=1, subject=subject, body_text=body, variables=variables,
                                   secret_bearing=secret_bearing, subject_reference=True, status="draft",
                                   content_sha256=digest(subject, body), synthetic=True)


def seed(apps, schema_editor):
    create_templates(apps.get_model("correspondence", "MessageTemplate"), apps.get_model("correspondence", "MessageTemplateVersion"))


def unseed(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    for key, (subject, body, *_rest) in SEEDS.items():
        # Only the seed this migration made: a later draft or an approved version (frozen, 0015 and 0021) stays.
        Version.objects.filter(template__key=key, version=1, status="draft", content_sha256=digest(subject, body)).delete()
        if not Version.objects.filter(template__key=key).exists():
            apps.get_model("correspondence", "MessageTemplate").objects.filter(key=key).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0021_subject_reference")]
    operations = [migrations.RunPython(seed, unseed)]
