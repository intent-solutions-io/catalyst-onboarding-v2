# bgl.8 (034 section 2.3 rows 27 and 28): the two service-sent signing mails as message templates, so the owner approves
# their wording on the template screen like every other template (211.7.7, D-29) and nothing in code holds the wording.
#
# - `agreement_link_nda`: the signing-link mail for the NDA.
# - `agreement_link_user_agreement`: the branded cover that carries the User Agreement's link, what to type on the last
#   page, and the Schedule A documents as bracketed slots the owner fills in.
#
# Both are seeded as unapproved placeholders (status draft, synthetic) with the link as a variable, so they are
# secret-bearing (016 3.1): never frozen into an approved message, never filed as a Sent copy; a local or synthetic
# environment sends the draft with a visible marker, a live environment refuses to send it (agreements.signing_mail).
# They are used only under CATALYST_AGREEMENT_DISTRIBUTION "service"; under "provider" the provider mails its own.
import hashlib

from django.db import migrations

LINK_KEY = "agreement_link_nda"
LINK_SUBJECT = "Please review and sign: [agreement title]"
LINK_BODY = (
    "PLACEHOLDER WORDING, NOT YET APPROVED.\n\n"
    "Hello $display_name,\n\n"
    "Please review and sign the [agreement title]:\n\n"
    "$link\n\n"
    "The link is yours alone; please do not forward it. [owner to state: whether there is a deadline, and whom to ask]\n\n"
    "[signature and company footer]\n"
)  # synthetic placeholder wording; never approved for real applicants (D-29)

COVER_KEY = "agreement_link_user_agreement"
COVER_SUBJECT = "Your [company] User Agreement"
COVER_BODY = (
    "PLACEHOLDER WORDING, NOT YET APPROVED.\n\n"
    "Hello $display_name,\n\n"
    "Thank you for signing the [first agreement title]. The next step is the [company] User Agreement.\n\n"
    "Review and sign the User Agreement:\n"
    "$link\n\n"
    "On the last page you will be asked to type your full legal name, your country and state or province of residence, "
    "a mailing address (street, line 2, city, state or region, postal code, country) and a phone number, then sign. "
    "[owner to state what the details are used for and that a correspondence address is acceptable]\n\n"
    "[owner to state what happens after signing: the countersignature, the copy the signing service sends, "
    "and what follows]\n\n"
    "Documents referenced in Schedule A\n"
    "[Schedule A document 1: title and link]\n"
    "[Schedule A document 2: title and link]\n"
    "[Schedule A document 3: title and link]\n"
    "[Schedule A document 4: title and link]\n\n"
    "[signature and company footer]\n"
)  # synthetic placeholder wording; never approved for real applicants (D-29)

VARIABLES = ["display_name", "link"]
# key -> (subject, body, purpose)
TEMPLATES = {
    LINK_KEY: (LINK_SUBJECT, LINK_BODY, "The service-sent signing link for the NDA (bgl.8; distribution 'service')"),
    COVER_KEY: (COVER_SUBJECT, COVER_BODY,
                "The branded cover carrying the User Agreement's signing link and what to type (bgl.8; distribution 'service')"),
}


def digest(subject, body):
    return hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()


def create_templates(Template, Version):
    """The two templates and their first drafts, unless already present (a re-applied migration keeps any later or
    approved version). Called by this migration and by tests that need the rows after the test reset truncated the
    correspondence tables (tests/test_agreement_parity.py)."""
    for key, (subject, body, purpose) in TEMPLATES.items():
        template, _ = Template.objects.get_or_create(key=key, defaults={"secret_bearing": True, "purpose": purpose})
        if not Version.objects.filter(template=template, version=1).exists():
            Version.objects.create(template=template, version=1, subject=subject, body_text=body, variables=list(VARIABLES),
                                   secret_bearing=True, status="draft", content_sha256=digest(subject, body), synthetic=True)


def seed(apps, schema_editor):
    create_templates(apps.get_model("correspondence", "MessageTemplate"), apps.get_model("correspondence", "MessageTemplateVersion"))


def unseed(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    for key, (subject, body, _) in TEMPLATES.items():
        # Only the seed this migration made: a later draft or an approved version (frozen, 0015) stays.
        Version.objects.filter(template__key=key, version=1, status="draft", content_sha256=digest(subject, body)).delete()
        if not Version.objects.filter(template__key=key).exists():
            apps.get_model("correspondence", "MessageTemplate").objects.filter(key=key).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0020_verification_template")]
    operations = [migrations.RunPython(seed, unseed)]
