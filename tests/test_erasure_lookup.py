"""9kg.72: a person invited who never applied can be named to the erasure command. The invite command prints the
invitation's public reference, and the owner-run lookup prints every reference held for an address, never the
address itself. Every person here is synthetic.
"""

import json
import sys

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from applications.models import Invitation
from tests.support import manage_as_owner, run
from tests.test_erasure import decided, erase, owner_scan, subject  # noqa: F401  (the `decided` fixture)
from tests.test_invitation import ensure_notice_templates

JUNE = "june.invited@example.test"


def test_9kg_72_an_invited_person_who_never_applied_is_named_by_reference_and_erased(privileged_reset, decided):
    ensure_notice_templates()
    issued = json.loads(manage_as_owner("catalyst_invite", JUNE, "--issued-by", "owner probe",
                                        "--note", "June Invited, cohort").stdout)
    reference = issued["invitation"]
    assert reference == str(Invitation.objects.get(email_key=JUNE).public_id)
    looked = manage_as_owner("catalyst_erasure_subjects", JUNE)
    found = json.loads(looked.stdout)
    assert found == {"applications": [], "invitations": [reference]}
    assert JUNE not in looked.stdout and "june" not in looked.stdout.lower()  # references only, never the address
    outcome = erase(privileged_reset, reference)  # the erasure takes an invitation's reference
    assert outcome.status == "erased"
    owner = privileged_reset.connect("owner", autocommit=True)
    assert owner_scan(owner, JUNE, "June Invited") == {}
    gone = run([sys.executable, "manage.py", "catalyst_erasure_subjects", JUNE], **_owner_env())
    assert gone.returncode == 1 and json.loads(gone.stdout) == {"applications": [], "invitations": []}


def test_9kg_72_the_lookup_lists_applications_too_and_refuses_in_web_and_worker(privileged_reset):
    app = subject("grace@example.test", "Grace Example")
    found = json.loads(manage_as_owner("catalyst_erasure_subjects", "Grace@Example.TEST").stdout)  # normalized
    assert found == {"applications": [str(app.public_ref)], "invitations": []}
    from config import runtime

    runtime.declare_process("worker")
    try:
        with pytest.raises(CommandError, match="not_a_management_process"):
            call_command("catalyst_erasure_subjects", "grace@example.test")
    finally:
        runtime.declare_process("management")
    with pytest.raises(CommandError, match="not an email address"):
        call_command("catalyst_erasure_subjects", "not-an-address")


def _owner_env():
    import os

    from django.conf import settings
    from django.db import connection

    return {"CATALYST_DB_NAME": connection.settings_dict["NAME"], "CATALYST_DB_USER": settings.CATALYST_DB_ROLES["owner"],
            "CATALYST_DB_PASSWORD": os.environ["CATALYST_DB_OWNER_PASSWORD"]}
