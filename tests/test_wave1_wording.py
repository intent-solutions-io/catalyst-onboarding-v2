"""D-53: the real wave 1 wording is added as draft, non-synthetic versions by `catalyst_seed_wording`, never approved
by it; once the owner approves them a live environment serves them, and the verification mail goes out in them.
"""

import json
from io import StringIO

from django.core.management import call_command

from applications import notices
from correspondence import outbound
from correspondence.models import MessageTemplateVersion
from correspondence.rendering import canonical_digest
from correspondence.wording import REAL
from tests.test_intake_notice import template_owner
from tests.test_invitation import ensure_notice_templates
from tests.test_verification_wording import ensure_template as ensure_verification_template


def seed() -> dict:
    out = StringIO()
    call_command("catalyst_seed_wording", stdout=out)
    return json.loads(out.getvalue())


def test_d53_the_real_wording_is_added_as_drafts_once_and_served_live_only_after_the_owner_approves(
        privileged_reset, settings):
    ensure_notice_templates()
    ensure_verification_template()
    first = seed()
    assert set(first) == set(REAL) and all(entry["added"] and entry["status"] == "draft" for entry in first.values())
    for key, (subject, body, variables) in REAL.items():
        version = MessageTemplateVersion.objects.get(template__key=key, version=first[key]["version"])
        assert (version.synthetic, version.status, version.variables) == (False, "draft", variables)
        assert version.content_sha256 == canonical_digest(subject, body) == first[key]["sha256"]
        assert "PLACEHOLDER" not in body and "[" not in body  # no unfilled slot reaches a real person
    again = seed()
    assert not any(entry["added"] for entry in again.values())  # idempotent: the same digest is never added twice
    settings.CATALYST_ENV = "production"
    assert notices.verification_withheld()  # nothing approved yet: still refused
    owner = template_owner(privileged_reset, "wave1-owner")
    for key in REAL:
        outbound.approve_template_version(
            MessageTemplateVersion.objects.get(template__key=key, version=first[key]["version"]).pk, owner)
    assert notices.data_notice().approved and "pseudonymous record" in notices.data_notice().text
    assert not notices.verification_withheld()
    mail = notices.invitation_mail()
    assert not mail.draft and "How your information is handled" not in mail.subject and "$notice" not in mail.body
