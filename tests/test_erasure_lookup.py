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
    looked = as_retention("catalyst_erasure_subjects", JUNE)
    assert looked.returncode == 0, looked.stderr
    found = json.loads(looked.stdout)
    assert found == {"applications": [], "invitations": [reference], "member_on_file": 0}
    assert JUNE not in looked.stdout and "june" not in looked.stdout.lower()  # references only, never the address
    outcome = erase(privileged_reset, reference)  # the erasure takes an invitation's reference
    assert outcome.status == "erased"
    owner = privileged_reset.connect("owner", autocommit=True)
    assert owner_scan(owner, JUNE, "June Invited") == {}
    gone = as_retention("catalyst_erasure_subjects", JUNE)
    assert gone.returncode == 3 and json.loads(gone.stdout) == {"applications": [], "invitations": [], "member_on_file": 0}


def test_9kg_72_the_lookup_runs_only_as_the_retention_login_lists_applications_and_refuses_bad_input(privileged_reset):
    app = subject("grace@example.test", "Grace Example")
    found = as_retention("catalyst_erasure_subjects", "Grace@Example.TEST")  # normalized
    assert found.returncode == 0 and json.loads(found.stdout)["applications"] == [str(app.public_ref)]
    for role in ("owner", "app"):  # never an oracle for another login (security review of PR #107)
        refused = run([sys.executable, "manage.py", "catalyst_erasure_subjects", "grace@example.test"], **_env(role))
        assert refused.returncode == 1 and "not_the_retention_role" in refused.stderr, (role, refused.stderr)
    for bad in ("Grace Example <grace@example.test>", "x" * 400 + "@example.test"):
        with pytest.raises(CommandError, match="a bare address is required"):
            call_command("catalyst_erasure_subjects", bad)
    from config import runtime

    runtime.declare_process("worker")
    try:
        with pytest.raises(CommandError, match="not_a_management_process"):
            call_command("catalyst_erasure_subjects", "grace@example.test")
    finally:
        runtime.declare_process("management")
    from config import runtime

    runtime.declare_process("worker")
    try:
        with pytest.raises(CommandError, match="not_a_management_process"):
            call_command("catalyst_erasure_subjects", "grace@example.test")
    finally:
        runtime.declare_process("management")
    with pytest.raises(CommandError, match="not an email address"):
        call_command("catalyst_erasure_subjects", "not-an-address")


def _env(role):
    import os

    from django.conf import settings
    from django.db import connection

    return {"CATALYST_DB_NAME": connection.settings_dict["NAME"], "CATALYST_DB_USER": settings.CATALYST_DB_ROLES[role],
            "CATALYST_DB_PASSWORD": os.environ[f"CATALYST_DB_{role.upper()}_PASSWORD"]}


def as_retention(*args):
    return run([sys.executable, "manage.py", *args], **_env("retention"))
