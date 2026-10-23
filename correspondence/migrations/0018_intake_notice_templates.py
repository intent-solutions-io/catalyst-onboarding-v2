# 9kg.52 (030 Q8, D-51): the one-paragraph data notice and the invitation mail as message templates, so the owner
# approves their wording on the template screen like every other template (211.7.7, D-29) and nothing in code holds
# the wording. Both are seeded as unapproved placeholders (status draft, synthetic): a local or synthetic environment
# renders a draft with a visible marker, a live environment refuses to serve it (applications.notices).
import hashlib

from django.db import migrations

DATA_NOTICE_KEY = "data_notice"
INVITATION_KEY = "invitation"

NOTICE_SUBJECT = "How your request is handled"
NOTICE_BODY = (
    "PLACEHOLDER WORDING, NOT YET APPROVED. What we collect: the name and email address you enter, the optional "
    "description of your work and credentials, any links you choose to give, and the record of your confirmation, "
    "your replies and the decision on your request. Who sees it: the named staff who handle requests, and nobody "
    "else; it is never shared or sold. No automated model reads your request and no link you give is fetched: a "
    "person reads it and a person makes every decision. You can withdraw your request at any time, and you can ask "
    "that your personal data be erased, by replying to any message from us; we confirm in writing what was done and "
    "keep only the minimal record that the law or an agreement you signed requires.\n"
)
INVITATION_SUBJECT = "An invitation to request access"
INVITATION_BODY = (
    "Hello,\n\n"
    "You are invited to request access. Use the request form at the address you were given, from this email "
    "address: a request from any other address receives no reply. The invitation is valid for a limited time and is "
    "spent when you confirm your email address.\n\n"
    "$notice\n"
    "If you did not expect this invitation, ignore it; nothing happens unless you submit a request.\n"
)  # synthetic placeholder wording; never approved for real members (D-29)


def digest(subject, body):
    return hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()


def create_templates(Template, Version):
    """The two templates and their first drafts. Called by this migration and, because the test reset truncates every
    correspondence table, by the tests that need them (tests/test_invitation.py)."""
    notice = Template.objects.create(key=DATA_NOTICE_KEY, secret_bearing=False,
                                     purpose="The one-paragraph data notice on the intake form and in the invitation (030 Q8)")
    Version.objects.create(template=notice, version=1, subject=NOTICE_SUBJECT, body_text=NOTICE_BODY, variables=[],
                           secret_bearing=False, status="draft", content_sha256=digest(NOTICE_SUBJECT, NOTICE_BODY),
                           synthetic=True)
    invitation = Template.objects.create(key=INVITATION_KEY, secret_bearing=False,
                                         purpose="The invitation mail the owner sends to an invited member; carries the data notice")
    Version.objects.create(template=invitation, version=1, subject=INVITATION_SUBJECT, body_text=INVITATION_BODY,
                           variables=["notice"], secret_bearing=False, status="draft",
                           content_sha256=digest(INVITATION_SUBJECT, INVITATION_BODY), synthetic=True)


def seed(apps, schema_editor):
    create_templates(apps.get_model("correspondence", "MessageTemplate"), apps.get_model("correspondence", "MessageTemplateVersion"))


def unseed(apps, schema_editor):
    Version = apps.get_model("correspondence", "MessageTemplateVersion")
    Template = apps.get_model("correspondence", "MessageTemplate")
    Version.objects.filter(template__key__in=[DATA_NOTICE_KEY, INVITATION_KEY]).delete()
    Template.objects.filter(key__in=[DATA_NOTICE_KEY, INVITATION_KEY]).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0017_provenance_freezes")]
    operations = [migrations.RunPython(seed, unseed)]
