"""9kg.52 (030 Q8 and Q4, D-51; 029 section 7): the one-paragraph data notice as an owner-approved template, rendered
on the request-access page in invitation mode and in the invitation mail from one version with a recorded version and
digest; and the owner-recorded "agreement on file, first-generation" flag per invited member.

The suite opens the intake mode per test (tests/conftest.py); each test here closes it where it proves the closed
behaviour. Template approval is the owner's act on the template screen (D-29); the tests approve through the same
service with a Template-owner account created on the owner path.
"""

import json
import os
import re
import sys

import psycopg
import pytest
from django.conf import settings as conf
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import ProgrammingError, connection
from django.test import Client
from django.urls import reverse

from applications import members, notices
from applications.models import Application, Invitation, MemberAgreementOnFile
from config import guards
from correspondence import outbound
from correspondence.models import MessageTemplateVersion
from correspondence.rendering import canonical_digest
from correspondence.roles import TEMPLATE_OWNER
from tests.support import ROOT, manage_as_owner, run
from tests.test_confirmation import intake
from tests.test_intake import FORM, counts, post
from tests.test_invitation import ADA, BOB, ensure_notice_templates, invite
from tests.test_staff import change_url, logged_in, make_user
from tests.test_system_health import health

NOTICE_PHRASE = "No automated model reads your request and no link you give is fetched"
INVITATION_PHRASE = "You are invited to request access"
LABEL = "NDA 2 and user agreement 3"


def closed(settings):
    settings.CATALYST_INTAKE_MODE = "invitation"
    ensure_notice_templates()


def seeded(key, version=1):
    return MessageTemplateVersion.objects.get(template__key=key, version=version)


def template_owner(privileged_reset, username="template-owner"):
    user = make_user(privileged_reset, username, group=False)
    privileged_reset.connect("owner", autocommit=True).execute(
        "INSERT INTO accounts_user_groups (user_id, group_id) SELECT %s, id FROM auth_group WHERE name = %s", [user.pk, TEMPLATE_OWNER])
    return user


def approve(privileged_reset, *keys):
    owner = template_owner(privileged_reset)
    for key in keys:
        outbound.approve_template_version(seeded(key).pk, owner)
    return owner


def notice_section(page: str) -> str | None:
    found = re.search(r'<section id="data-notice".*?</section>', page, flags=re.S)
    return found.group(0) if found else None


# --- the page: one approved template, its version and digest ----------------------------------------------------

def test_9kg_52_the_approved_notice_renders_on_the_intake_page_in_invitation_mode_with_its_version_and_digest(privileged_reset, settings):
    closed(settings)
    approve(privileged_reset, notices.DATA_NOTICE)
    version = seeded(notices.DATA_NOTICE)
    assert version.status == "approved" and version.content_sha256 == canonical_digest(version.subject, version.body_text)
    client = Client()
    page = client.get(FORM).content.decode()
    section = notice_section(page)
    assert section is not None and NOTICE_PHRASE in section and "Draft notice" not in page
    assert f'data-notice-version="{version.version}"' in section and f'data-notice-sha256="{version.content_sha256}"' in section
    assert "PLACEHOLDER WORDING" in section  # the seeded placeholder says so itself until the owner replaces it
    wording = notices.data_notice()
    assert (wording.approved, wording.version, wording.sha256) == (True, 1, version.content_sha256)
    assert wording.text == version.body_text and wording.display == wording.text
    # A rejected submission re-renders the form with the notice still on it.
    rejected = post(client, email="")
    assert rejected.status_code == 200 and NOTICE_PHRASE in rejected.content.decode()
    # A newer approved version replaces the older one on the page, with its own version and digest.
    newer_body = "Approved placeholder, second wording: nothing is read by a model and nothing is fetched.\n"
    newer = MessageTemplateVersion.objects.create(
        template=version.template, version=2, subject=version.subject, body_text=newer_body, variables=[],
        content_sha256=canonical_digest(version.subject, newer_body))
    outbound.approve_template_version(newer.pk, template_owner(privileged_reset, "template-owner-2"))
    page = client.get(FORM).content.decode()
    assert newer_body.strip() in page and NOTICE_PHRASE not in page and 'data-notice-version="2"' in page
    assert f'data-notice-sha256="{newer.content_sha256}"' in page
    # With the mode open the page is the S1 page: no notice section at all.
    settings.CATALYST_INTAKE_MODE = "open"
    page = client.get(FORM).content.decode()
    assert notice_section(page) is None and "notice" not in page.lower()


# --- unapproved: a marked draft outside a live environment, withheld in one --------------------------------------

@pytest.mark.django_db
def test_9kg_52_an_unapproved_notice_is_marked_draft_outside_a_live_environment_and_withheld_in_one(settings, caplog):
    closed(settings)
    assert seeded(notices.DATA_NOTICE).status == "draft" and seeded(notices.DATA_NOTICE).synthetic is True
    assert guards.DRAFT_WORDING_ENVIRONMENTS == {"development", "test", "staging"}
    assert not guards.draft_wording_allowed("production") and not guards.draft_wording_allowed("")
    client = Client()
    page = client.get(FORM).content.decode()
    section = notice_section(page)
    assert section is not None and "Draft notice." in section and NOTICE_PHRASE in section and 'data-notice-version="1"' in section
    wording = notices.data_notice()
    assert wording.draft and wording.display.startswith(notices.DRAFT_MARKER) and NOTICE_PHRASE in wording.text
    code, report = health()
    assert code == 0 and report["intake"]["data_notice"]["status"] == "draft" and report["intake"]["anomalies"] == []
    # A live environment: the page is withheld with the one try-again page, nothing is recorded, a reason code is logged.
    settings.CATALYST_ENV = "production"
    with pytest.raises(notices.Unavailable, match="data_notice_not_approved"):
        notices.data_notice()
    before = counts()
    withheld = client.get(FORM)
    assert withheld.status_code == 503 and b"Please try again" in withheld.content
    assert NOTICE_PHRASE.encode() not in withheld.content and b"data-notice" not in withheld.content
    submitted = post(client, email=ADA)
    assert submitted.status_code == 503 and counts() == before
    assert caplog.text.count("intake page withheld: data_notice_not_approved") == 2
    code, report = health()
    assert code == 1 and report["intake"]["anomalies"] == ["data_notice_unapproved"]
    # The open intake does not need the notice, even there.
    settings.CATALYST_INTAKE_MODE = "open"
    assert client.get(FORM).status_code == 200 and health()[1]["intake"]["anomalies"] == []


# --- the invitation mail: the same template, recorded on the invitation ------------------------------------------

def test_9kg_52_the_invitation_mail_carries_the_notice_and_the_invitation_records_its_version_and_digest(privileged_reset, settings):
    closed(settings)
    notice_version = seeded(notices.DATA_NOTICE)
    # A live environment issues nothing while the wording is unapproved: refused before any write (in process, so the
    # settings override holds; the refusal precedes the insert the application role could not make anyway).
    settings.CATALYST_ENV = "production"
    with pytest.raises(CommandError, match=r"refused \(data_notice_not_approved\)"):
        call_command("catalyst_invite", BOB, "--issued-by", "owner probe")
    assert Invitation.objects.count() == 0
    settings.CATALYST_ENV = "test"
    # Outside a live environment the draft is issued with its marker, and the row records which notice the mail carries.
    first = manage_as_owner("catalyst_invite", "Ada@Example.TEST", "--issued-by", "owner probe")
    issued = json.loads(first.stdout)
    mail = issued["mail"]
    assert issued["issued"] is True and mail["draft"] is True
    assert mail["body"].count(notices.DRAFT_MARKER) == 2  # the invitation wording and the notice are both drafts
    assert NOTICE_PHRASE in mail["body"] and INVITATION_PHRASE in mail["body"] and "$notice" not in mail["body"]
    assert mail["subject"] == seeded(notices.INVITATION).subject
    assert (mail["notice_version"], mail["notice_sha256"]) == (1, notice_version.content_sha256)
    assert (mail["template_version"], mail["template_sha256"]) == (1, seeded(notices.INVITATION).content_sha256)
    assert ADA not in (first.stdout + first.stderr).lower()
    row = Invitation.objects.get()
    assert (row.notice_template_version, row.notice_sha256) == (1, notice_version.content_sha256)
    # Approved: no marker anywhere, the same notice text, the recorded digest is the approved version's.
    approve(privileged_reset, notices.DATA_NOTICE, notices.INVITATION)
    second = json.loads(manage_as_owner("catalyst_invite", ADA, "--issued-by", "owner probe").stdout)
    assert second["superseded"] == 1 and second["mail"]["draft"] is False
    assert notices.DRAFT_MARKER not in second["mail"]["body"] and NOTICE_PHRASE in second["mail"]["body"]
    assert second["mail"]["body"].endswith("nothing happens unless you submit a request.\n")
    assert notices.invitation_mail().body == second["mail"]["body"]
    newest = Invitation.objects.order_by("-id").first()
    assert (newest.notice_template_version, newest.notice_sha256) == (1, notice_version.content_sha256)
    # The record is fixed with the rest of the issuance: not even the owner changes it.
    owner = privileged_reset.connect("owner", autocommit=True)
    for sql in ("UPDATE applications_invitation SET notice_sha256 = repeat('0', 64) WHERE id = %s",
                "UPDATE applications_invitation SET notice_template_version = 2 WHERE id = %s"):
        with pytest.raises(psycopg.Error, match="invitation: UPDATE refused"):
            owner.execute(sql, [newest.id])
    assert Invitation.objects.get(pk=newest.pk).notice_sha256 == notice_version.content_sha256


# --- the wording is a template the owner approves, never a constant ----------------------------------------------

def test_9kg_52_the_wording_is_an_owner_approved_template_and_not_a_constant(privileged_reset):
    ensure_notice_templates()
    # The wording lives in the seed migration (the template's first draft) and nowhere else in the code or the pages.
    holders = sorted(str(p.relative_to(ROOT)) for app in ("applications", "config", "correspondence", "workflow")
                     for p in (ROOT / app).rglob("*") if p.suffix in (".py", ".html", ".txt") and NOTICE_PHRASE in p.read_text())
    assert holders == ["correspondence/migrations/0018_intake_notice_templates.py"]
    # Both templates are on the owner's template screen and unapproved until the owner acts.
    owner = template_owner(privileged_reset)
    screen = logged_in(owner).get(reverse("correspondence_staff:templates")).content.decode()
    assert "data_notice" in screen and "invitation" in screen
    for key in (notices.DATA_NOTICE, notices.INVITATION):
        assert seeded(key).status == "draft" and seeded(key).approved_by == ""
    # Approval is the owner's permission (D-29): a read-only staff account is refused, the Template owner approves,
    # and the approver and time are recorded on the version.
    reader = make_user(privileged_reset, "reader")
    with pytest.raises(PermissionDenied):
        outbound.approve_template_version(seeded(notices.DATA_NOTICE).pk, reader)
    approved = outbound.approve_template_version(seeded(notices.DATA_NOTICE).pk, owner)
    assert approved.status == "approved" and approved.approved_by == f"user:{owner.pk}" and approved.approved_at is not None
    assert seeded(notices.INVITATION).status == "draft"  # each template is approved on its own
    # The invitation template may carry the notice and nothing else: its allow-list is the one variable.
    assert seeded(notices.INVITATION).variables == ["notice"] and seeded(notices.DATA_NOTICE).variables == []
    assert notices.status(notices.DATA_NOTICE) == {"status": "approved", "version": 1, "sha256": approved.content_sha256}
    assert notices.status(notices.INVITATION)["status"] == "draft" and notices.status("no_such_template")["status"] == "missing"


# --- the member-on-file flag: owner-run, audited, fixed, visible ---------------------------------------------------

def test_9kg_52_the_member_on_file_flag_is_recorded_only_by_the_owner_run_command_and_fixed_by_the_database(privileged_reset):
    first = manage_as_owner("catalyst_member_on_file", "Ada@Example.TEST", "--agreement-version", f"  {LABEL}  ",
                            "--completion-verified", "--recorded-by", "owner probe", "--note", "from the private roster")
    recorded = json.loads(first.stdout)
    assert recorded == {"recorded": True, "agreement_version": LABEL, "completion_verified": True,
                        "recorded_at": recorded["recorded_at"], "superseded": 0}
    assert "member on file recorded by owner probe" in first.stderr  # the audit line names the recorder, never the address
    assert ADA not in (first.stdout + first.stderr).lower() and "Ada@Example.TEST" not in first.stdout + first.stderr
    row = MemberAgreementOnFile.objects.get()
    assert (row.email_key, row.agreement_version, row.completion_verified, row.recorded_by, row.note, row.superseded_at) == (
        ADA, LABEL, True, "owner probe", "from the private roster", None)
    # A correction supersedes the live row; the history keeps both.
    second = json.loads(manage_as_owner("catalyst_member_on_file", ADA, "--agreement-version", "NDA 2 and user agreement 4",
                                        "--completion-verified", "--recorded-by", "owner probe").stdout)
    assert second["superseded"] == 1
    old, new = MemberAgreementOnFile.objects.order_by("id")
    assert old.superseded_at is not None and new.superseded_at is None and new.agreement_version == "NDA 2 and user agreement 4"
    # Refused inputs (the owner env, so each refusal is the command's, not a privilege): no verified completion means
    # a new participant and nothing recorded; a reference, a link, an identifier or a copy is never a version label.
    owner_env = dict(CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=conf.CATALYST_DB_ROLES["owner"],
                     CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
    refusals = {
        "new participant": [BOB, "--agreement-version", LABEL, "--recorded-by", "x"],
        "looks_like_a_reference": [BOB, "--agreement-version", "https://example.test/agreements/nda.pdf", "--completion-verified", "--recorded-by", "x"],
        "looks_like_a_reference ": [BOB, "--agreement-version", "roster/row 12", "--completion-verified", "--recorded-by", "x"],
        "looks_like_an_identifier": [BOB, "--agreement-version", "NDA 20250101001", "--completion-verified", "--recorded-by", "x"],
        "too_long": [BOB, "--agreement-version", "v" * 101, "--completion-verified", "--recorded-by", "x"],
        "empty": [BOB, "--agreement-version", "   ", "--completion-verified", "--recorded-by", "x"],
        "not an email address": ["not-an-address", "--agreement-version", LABEL, "--completion-verified", "--recorded-by", "x"],
        "--recorded-by": [BOB, "--agreement-version", LABEL, "--completion-verified", "--recorded-by", " "],
    }
    for expected, args in refusals.items():
        refused = run([sys.executable, "manage.py", "catalyst_member_on_file", *args], **owner_env)
        assert refused.returncode != 0 and expected.strip() in refused.stderr, (args, refused.stderr)
    assert MemberAgreementOnFile.objects.count() == 2
    assert members.check_label("  NDA  2 ") == "NDA 2"
    # The application role reads the state for the dossier and may do nothing else; the command as that role is refused.
    with pytest.raises(ProgrammingError, match="permission denied for table applications_memberagreementonfile"):
        MemberAgreementOnFile.objects.create(email_key=BOB, agreement_version=LABEL, completion_verified=True, recorded_by="web")
    app_role = run([sys.executable, "manage.py", "catalyst_member_on_file", BOB, "--agreement-version", LABEL,
                    "--completion-verified", "--recorded-by", "web"],
                   CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=conf.CATALYST_DB_ROLES["app"],
                   CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"])
    assert app_role.returncode != 0 and "could not be written (ProgrammingError)" in app_role.stderr
    app_conn = privileged_reset.connect("app", autocommit=True)
    assert app_conn.execute("SELECT count(*) FROM applications_memberagreementonfile").fetchone()[0] == 2
    for sql in ("UPDATE applications_memberagreementonfile SET superseded_at = now() WHERE id = %s",
                "DELETE FROM applications_memberagreementonfile WHERE id = %s"):
        with pytest.raises(psycopg.Error, match="permission denied"):
            app_conn.execute(sql, [new.id])
    # Not even the owner changes a record, re-supersedes, deletes or truncates; the database refuses an unverified row.
    owner = privileged_reset.connect("owner", autocommit=True)
    for sql, target in (("UPDATE applications_memberagreementonfile SET agreement_version = 'other' WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET recorded_by = 'someone else' WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET completion_verified = false WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET email_key = 'bob@example.test' WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET superseded_at = now() + interval '1 hour' WHERE id = %s", old.id),
                        ("DELETE FROM applications_memberagreementonfile WHERE id = %s", old.id)):
        with pytest.raises(psycopg.Error, match="member on file: (UPDATE|DELETE) refused"):
            owner.execute(sql, [target])
    with pytest.raises(psycopg.Error, match="append-only"):
        owner.execute("TRUNCATE applications_memberagreementonfile")
    with pytest.raises(psycopg.Error, match="member_on_file_completion_verified"):
        owner.execute("INSERT INTO applications_memberagreementonfile (public_id, email_key, agreement_version, completion_verified,"
                      " recorded_by, note) VALUES (gen_random_uuid(), %s, %s, false, 'owner', '')", [BOB, LABEL])
    assert MemberAgreementOnFile.objects.count() == 2


def test_9kg_52_the_dossier_shows_the_member_on_file_state(privileged_reset, settings):
    closed(settings)
    owner = privileged_reset.connect("owner", autocommit=True)
    invite(owner, ADA, issued_by="the owner")
    app = intake(Client())
    staff = logged_in(make_user(privileged_reset, "dossier-staff"))
    before = staff.get(change_url(app))
    assert before.status_code == 200
    assert "new participant: no first-generation agreement on file; signs the current versions" in before.content.decode()
    assert members.on_file(app) is None
    manage_as_owner("catalyst_member_on_file", ADA, "--agreement-version", LABEL, "--completion-verified", "--recorded-by", "the owner")
    after = staff.get(change_url(app)).content.decode()
    assert f"agreement on file, first-generation: {LABEL}; completion verified; recorded by the owner at " in after
    assert str(MemberAgreementOnFile.objects.get().public_id) not in after
    assert members.describe(app).startswith(f"agreement on file, first-generation: {LABEL}")
    # The state follows the address, not the application: another applicant is a new participant.
    invite(owner, BOB)
    other = intake(Client(), email=BOB, name="Bob Example")
    assert members.on_file(other) is None and "new participant" in staff.get(change_url(other)).content.decode()
    assert Application.objects.count() == 2
