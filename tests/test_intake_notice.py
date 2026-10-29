"""9kg.52 (030 Q8 and Q4, D-51; 029 section 17.2): the one-paragraph data notice as an owner-approved template, rendered
on the request-access page in invitation mode and in the invitation mail from one version with a recorded version and
digest; the owner-recorded first-generation agreement-on-file record per invited member, which the agreement path
reads as "referenced" and the decision service reads as "no v2 decline".

The suite opens the intake mode per test (tests/conftest.py); each test here closes it where it proves the closed
behaviour. Template approval is the owner's act on the template screen (D-29); the tests approve through the same
service, or through the screen where the screen is the point, with a Template-owner account created on the owner path.
"""

import json
import logging
import os
import re
import sys
from types import SimpleNamespace

import psycopg
import pytest
from django.conf import settings as conf
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, ProgrammingError, connection
from django.test import Client
from django.urls import reverse

from agreements import completion
from agreements.models import AgreementInstance, AgreementType
from applications import invitations, members, notices, views
from applications.models import Application, Invitation, MemberAgreementOnFile
from assessments import decisions
from assessments.models import QualificationDecision
from assessments.services import Refused as DecisionRefused
from config import guards
from correspondence import outbound
from correspondence.models import MessageTemplateVersion, StaffItem
from correspondence.rendering import canonical_digest
from correspondence.roles import TEMPLATE_OWNER
from tests.support import ROOT, manage_as_owner, run
from tests.test_agreement_completion import h  # noqa: F401  (fixture: g plus a User Agreement template)
from tests.test_agreements import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, p2, run_worker, tls,
)
from tests.test_confirmation import intake
from tests.test_decision import decide, rationale, ready_app
from tests.test_intake import FORM, counts, post
from tests.test_invitation import ADA, BOB, ensure_notice_templates, invite
from tests.test_staff import change_url, logged_in, make_user
from tests.test_system_health import health
from workflow.models import PendingAction

NOTICE_PHRASE = "No automated model reads your request"
INVITATION_PHRASE = "You are invited to request access"
LINK_CLAIM = "We check only the links you give"
LABEL_A, LABEL_B, LABEL_C = "agreement label A", "agreement label B", "agreement label C"


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


def approve_notice(privileged_reset, *keys):
    owner = template_owner(privileged_reset)
    for key in keys:
        outbound.approve_template_version(seeded(key).pk, owner)
    return owner


def real_version(privileged_reset, key, version, body, owner=None):
    """A newer version whose wording is real (not a synthetic placeholder), approved by the owner."""
    old = seeded(key)
    new = MessageTemplateVersion.objects.create(
        template=old.template, version=version, subject=old.subject, body_text=body, variables=list(old.variables),
        content_sha256=canonical_digest(old.subject, body), synthetic=False)
    return outbound.approve_template_version(new.pk, owner or template_owner(privileged_reset, f"owner-v{version}"))


def notice_section(page: str) -> str | None:
    found = re.search(r'<section id="data-notice".*?</section>', page, flags=re.S)
    return found.group(0) if found else None


def owner_env():
    return dict(CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=conf.CATALYST_DB_ROLES["owner"],
                CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])


def on_file(email, *args):
    return json.loads(manage_as_owner("catalyst_member_on_file", email, *args, "--completion-verified",
                                      "--recorded-by", "owner probe").stdout)


@pytest.fixture
def quiet_withheld(monkeypatch):
    monkeypatch.setattr(views, "_withheld_logged", {})
    # These tests are about the data notice alone; the verification mail's own refusal (9kg.80) is tested in
    # tests/test_verification_wording.py, so here it counts as approved.
    monkeypatch.setattr(notices, "verification_withheld", lambda: False)


# --- the page: one approved template, its version and digest ----------------------------------------------------

def test_9kg_52_the_approved_notice_renders_on_the_intake_page_in_invitation_mode_with_its_version_and_digest(privileged_reset, settings):
    closed(settings)
    approve_notice(privileged_reset, notices.DATA_NOTICE)
    version = seeded(notices.DATA_NOTICE)
    assert version.status == "approved" and version.content_sha256 == canonical_digest(version.subject, version.body_text)
    client = Client()
    page = client.get(FORM).content.decode()
    section = notice_section(page)
    assert section is not None and NOTICE_PHRASE in section and "Draft notice" not in page
    assert f'data-notice-version="{version.version}"' in section and f'data-notice-sha256="{version.content_sha256}"' in section
    wording = notices.data_notice()
    assert (wording.approved, wording.version, wording.sha256) == (True, 1, version.content_sha256)
    assert wording.text == version.body_text and wording.display == wording.text
    rejected = post(client, email="")  # a rejected submission re-renders the form with the notice on it
    assert rejected.status_code == 200 and NOTICE_PHRASE in rejected.content.decode()
    newer = real_version(privileged_reset, notices.DATA_NOTICE, 2,
                         "Approved wording, second version: nothing is read by a model and nothing is fetched.\n")
    page = client.get(FORM).content.decode()
    assert "second version" in page and NOTICE_PHRASE not in page and 'data-notice-version="2"' in page
    assert f'data-notice-sha256="{newer.content_sha256}"' in page
    settings.CATALYST_INTAKE_MODE = "open"  # the open intake is the S1 page: no notice section at all
    page = client.get(FORM).content.decode()
    assert notice_section(page) is None and "notice" not in page.lower()


@pytest.mark.django_db
def test_9kg_52_the_invitation_mode_page_makes_no_link_checking_claim_and_the_notice_claims_match_the_guards(settings):
    """The notice says no model reads a request and no link is fetched; the guards are what make that true outside
    the synthetic environments, so loosening either guard fails here."""
    settings.CATALYST_INTAKE_MODE = "invitation"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(notices, "data_notice", lambda: notices.Wording("data_notice", 1, "0" * 64, "s", "text", approved=True))
        page = Client().get(FORM).content.decode()
    assert "Access is currently by invitation" in page and LINK_CLAIM not in page
    settings.CATALYST_INTAKE_MODE = "open"
    assert LINK_CLAIM in Client().get(FORM).content.decode()  # the open S1 form keeps its own sentence
    from importlib import import_module

    body = import_module("correspondence.migrations.0018_intake_notice_templates").NOTICE_BODY
    assert "No automated model reads your request and no link you give is fetched" in body
    for live in ("production", "development", ""):
        fetching = SimpleNamespace(CATALYST_ENV=live, CATALYST_EVIDENCE_ALLOWED_HOSTS=["example.org"],
                                   CATALYST_EVIDENCE_FIXTURE_ADDRESS="", CATALYST_EVIDENCE_CA_FILE="")
        assert guards.evidence_problems(fetching, {}), live  # no link may be fetchable outside test and staging
        for model in ("test", "minimax", "openai:gpt"):
            assert guards.assessment_problems(SimpleNamespace(CATALYST_ENV=live, CATALYST_ASSESSMENT_MODEL=model), {}), (live, model)
        assert guards.assessment_problems(SimpleNamespace(CATALYST_ENV=live, CATALYST_ASSESSMENT_MODEL="none"), {}) == []


def test_9kg_52_draft_wording_is_allowed_only_in_the_local_and_synthetic_environments():
    assert guards.DRAFT_WORDING_ENVIRONMENTS <= guards.SYNTHETIC_ENVIRONMENTS | {"development"}
    assert guards.DRAFT_WORDING_ENVIRONMENTS <= guards.ALLOWED_ENVIRONMENTS
    for name in ("production", "prod", "live", "Staging", "", "pilot"):
        assert not guards.draft_wording_allowed(name), name


# --- unapproved, synthetic or withdrawn: a marked draft outside a live environment, withheld in one ---------------

@pytest.mark.django_db
def test_9kg_52_an_unapproved_notice_is_marked_draft_outside_a_live_environment_and_withheld_in_one(settings, caplog, quiet_withheld):
    closed(settings)
    assert seeded(notices.DATA_NOTICE).status == "draft" and seeded(notices.DATA_NOTICE).synthetic is True
    client = Client()
    for environment in ("test", "staging", "development"):  # staging is a synthetic environment: marked, not withheld
        settings.CATALYST_ENV = environment
        section = notice_section(client.get(FORM).content.decode())
        assert section is not None and "Draft notice." in section and NOTICE_PHRASE in section, environment
        assert 'data-notice-version="1"' in section
    settings.CATALYST_ENV = "test"
    rerender = post(client, email="")  # a POST that re-renders the form keeps the marked draft
    assert rerender.status_code == 200 and "Draft notice." in rerender.content.decode()
    wording = notices.data_notice()
    assert wording.draft and wording.display.startswith(notices.DRAFT_MARKER) and NOTICE_PHRASE in wording.text
    code, report = health()
    assert code == 0 and report["intake"]["data_notice"]["status"] == "draft" and report["intake"]["anomalies"] == []
    # A live environment: withheld with the one try-again page, nothing recorded, the reason logged once per window.
    settings.CATALYST_ENV = "production"
    with pytest.raises(notices.Unavailable, match="data_notice_not_approved"):
        notices.data_notice()
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="applications.views")
    before = counts()
    withheld = client.get(FORM)
    assert withheld.status_code == 503 and b"Please try again" in withheld.content
    assert NOTICE_PHRASE.encode() not in withheld.content and b"data-notice" not in withheld.content
    assert post(client, email=ADA).status_code == 503 and counts() == before
    assert client.get(FORM).status_code == 503
    assert caplog.text.count("intake page withheld: data_notice_not_approved") == 1  # sampled, not one per request
    code, report = health()
    assert code == 1 and report["intake"]["anomalies"] == ["data_notice_unapproved"]
    settings.CATALYST_INTAKE_MODE = "open"  # the open intake does not need the notice, even there
    assert client.get(FORM).status_code == 200 and health()[1]["intake"]["anomalies"] == []
    # A stray `$` in a newer draft is a refusal with a reason code, never a server error (last: versions are kept).
    settings.CATALYST_ENV, settings.CATALYST_INTAKE_MODE = "test", "invitation"
    old = seeded(notices.DATA_NOTICE)
    MessageTemplateVersion.objects.create(template=old.template, version=2, subject=old.subject, body_text="Costs $ nothing.\n",
                                          variables=[], content_sha256=canonical_digest(old.subject, "Costs $ nothing.\n"))
    with pytest.raises(notices.Unavailable, match="data_notice_invalid_placeholder"):
        notices.data_notice()
    assert client.get(FORM).status_code == 503


def test_9kg_52_an_approved_synthetic_or_retired_notice_is_refused_in_a_live_environment(privileged_reset, settings, quiet_withheld):
    closed(settings)
    owner = approve_notice(privileged_reset, notices.DATA_NOTICE)
    assert seeded(notices.DATA_NOTICE).status == "approved" and seeded(notices.DATA_NOTICE).synthetic is True
    assert notices.data_notice().approved  # a synthetic environment serves it (a drill)
    settings.CATALYST_ENV = "production"
    with pytest.raises(notices.Unavailable, match="data_notice_synthetic"):
        notices.data_notice()  # approved, but still the placeholder: never shown to a real person
    assert Client().get(FORM).status_code == 503
    code, report = health()
    assert code == 1 and report["intake"]["anomalies"] == ["data_notice_unapproved"]
    assert report["intake"]["data_notice"] == {"status": "approved", "version": 1, "synthetic": True,
                                               "sha256": seeded(notices.DATA_NOTICE).content_sha256}
    real = real_version(privileged_reset, notices.DATA_NOTICE, 2, "Real wording, approved by the owner.\n", owner)
    wording = notices.data_notice()  # real and approved: served in a live environment
    assert (wording.version, wording.sha256, wording.approved) == (2, real.content_sha256, True)
    assert Client().get(FORM).status_code == 200 and health()[1]["intake"]["anomalies"] == []
    # Withdrawn: the newest approved-or-retired version is retired, so nothing older is served in its place.
    privileged_reset.connect("owner", autocommit=True).execute(
        "UPDATE correspondence_messagetemplateversion SET status = 'retired' WHERE id = %s", [real.pk])
    with pytest.raises(notices.Unavailable, match="data_notice_retired"):
        notices.data_notice()
    assert Client().get(FORM).status_code == 503 and health()[1]["intake"]["data_notice"]["status"] == "retired"


# --- the invitation mail: the same template, recorded on the invitation ------------------------------------------

def test_9kg_52_the_invitation_mail_carries_the_notice_and_the_invitation_records_its_version_and_digest(privileged_reset, settings, monkeypatch):
    closed(settings)
    notice_version = seeded(notices.DATA_NOTICE)
    settings.CATALYST_ENV = "production"  # a live environment issues nothing while the wording is unapproved
    with pytest.raises(CommandError, match=r"refused \(data_notice_not_approved\)"):
        call_command("catalyst_invite", BOB, "--issued-by", "owner probe")
    assert Invitation.objects.count() == 0
    settings.CATALYST_ENV = "test"
    first = manage_as_owner("catalyst_invite", "Ada@Example.TEST", "--issued-by", "owner probe")
    mail = json.loads(first.stdout)["mail"]
    assert mail["draft"] is True and mail["body"].count(notices.DRAFT_MARKER) == 2  # both wordings are drafts
    assert NOTICE_PHRASE in mail["body"] and INVITATION_PHRASE in mail["body"] and "$notice" not in mail["body"]
    assert (mail["notice_version"], mail["notice_sha256"]) == (1, notice_version.content_sha256)
    assert (mail["template_version"], mail["template_sha256"]) == (1, seeded(notices.INVITATION).content_sha256)
    assert ADA not in (first.stdout + first.stderr).lower()
    row = Invitation.objects.get()
    assert (row.notice_template_version, row.notice_sha256, row.mail_template_sha256) == (
        1, notice_version.content_sha256, seeded(notices.INVITATION).content_sha256)
    approve_notice(privileged_reset, notices.DATA_NOTICE, notices.INVITATION)
    text = manage_as_owner("catalyst_invite", ADA, "--issued-by", "owner probe", "--format", "text").stdout
    assert text.startswith(f"Subject: {seeded(notices.INVITATION).subject}\n\n") and NOTICE_PHRASE in text
    assert notices.DRAFT_MARKER not in text and "-- recorded: data notice version 1" in text and "DRAFT" not in text
    assert text.split("\n-- recorded:")[0].endswith("nothing happens unless you submit a request.\n")
    assert ADA not in text.lower()
    newest = Invitation.objects.order_by("-id").first()
    assert Invitation.objects.filter(superseded_at__isnull=False).count() == 1 and newest.notice_sha256 == notice_version.content_sha256
    owner = privileged_reset.connect("owner", autocommit=True)  # the record is fixed with the rest of the issuance
    for column, value in (("notice_sha256", "0" * 64), ("notice_template_version", 2), ("mail_template_sha256", "0" * 64)):
        with pytest.raises(psycopg.Error, match="invitation: UPDATE refused"):
            owner.execute(f"UPDATE applications_invitation SET {column} = %s WHERE id = %s", [value, newest.id])
    # A concurrent run that commits first is reported as such, never as a missing privilege.
    monkeypatch.setattr(invitations, "issue", lambda *_args, **_kwargs: (_ for _ in ()).throw(IntegrityError("dup")))
    with pytest.raises(CommandError, match=r"refused \(concurrent_issue\)"):
        call_command("catalyst_invite", ADA, "--issued-by", "owner probe")


# --- the wording is a template the owner approves, never a constant ----------------------------------------------

def test_9kg_52_the_wording_is_an_owner_approved_template_and_not_a_constant(privileged_reset):
    ensure_notice_templates()
    holders = sorted(str(p.relative_to(ROOT)) for app in ("applications", "config", "correspondence", "workflow", "agreements")
                     for p in (ROOT / app).rglob("*") if p.suffix in (".py", ".html", ".txt") and NOTICE_PHRASE in p.read_text())
    assert holders == ["correspondence/migrations/0018_intake_notice_templates.py"]
    body = seeded(notices.DATA_NOTICE).body_text
    for slot in ("[counsel to state any other recipient or processor]", "[counsel to state the withdrawal route]",
                 "[counsel to state the erasure route"):
        assert slot in body  # the claims counsel must make are slots, not placeholder promises
    for content in ("What we collect", "Who sees it", "No automated model reads", "no link you give is fetched",
                    "How to withdraw", "How to request erasure"):
        assert content in body  # 030 Q8's content list
    owner = template_owner(privileged_reset)
    screen = logged_in(owner)
    listing = screen.get(reverse("correspondence_staff:templates")).content.decode()
    assert "data_notice" in listing and "invitation" in listing
    for key in (notices.DATA_NOTICE, notices.INVITATION):
        assert seeded(key).status == "draft" and seeded(key).approved_by == ""
    with pytest.raises(PermissionDenied):
        outbound.approve_template_version(seeded(notices.DATA_NOTICE).pk, make_user(privileged_reset, "reader"))
    # Through the screen, the owner approves exactly what was shown: a stale digest is refused.
    version = seeded(notices.DATA_NOTICE)
    page = screen.get(reverse("correspondence_staff:template", args=[version.pk])).content.decode()
    assert "Approve exactly this version" in page and version.content_sha256 in page
    stale = screen.post(reverse("correspondence_staff:approve_template", args=[version.pk]), {"digest": "0" * 64}, follow=True)
    assert "Refused: template_changed_since_shown" in stale.content.decode() and seeded(notices.DATA_NOTICE).status == "draft"
    screen.post(reverse("correspondence_staff:approve_template", args=[version.pk]), {"digest": version.content_sha256})
    approved = seeded(notices.DATA_NOTICE)
    assert approved.status == "approved" and approved.approved_by == f"user:{owner.pk}" and approved.approved_at is not None
    assert seeded(notices.INVITATION).status == "draft"  # each template is approved on its own
    assert seeded(notices.INVITATION).variables == ["notice"] and seeded(notices.DATA_NOTICE).variables == []
    assert notices.status(notices.DATA_NOTICE) == {"status": "approved", "version": 1, "sha256": approved.content_sha256,
                                                   "synthetic": True}
    assert notices.status("no_such_template")["status"] == "missing"


# --- the member-on-file record: owner-run, idempotent, plain labels, fixed --------------------------------------

def test_9kg_52_the_coverable_types_are_the_seeded_agreement_types(db):
    assert members.COVERABLE == tuple(AgreementType.objects.filter(required=True).order_by("order").values_list("key", flat=True))


def test_9kg_52_the_owner_records_a_member_on_file_idempotently_and_corrects_only_with_correct(privileged_reset, settings):
    invite(privileged_reset.connect("owner", autocommit=True), ADA)
    first = manage_as_owner("catalyst_member_on_file", "Ada@Example.TEST", "--nda", f"  {LABEL_A}  ", "--user-agreement",
                            LABEL_B, "--completion-verified", "--recorded-by", "owner probe")
    recorded = json.loads(first.stdout)
    assert (recorded["outcome"], recorded["covers"], recorded["completion_verified"]) == (
        "recorded", {"nda": LABEL_A, "user_agreement": LABEL_B}, True)
    assert "member on file recorded by owner probe" in first.stderr and ADA not in (first.stdout + first.stderr).lower()
    row = MemberAgreementOnFile.objects.get()
    assert (row.email_key, row.covers, row.completion_verified, row.recorded_by, row.superseded_at) == (
        ADA, {"nda": LABEL_A, "user_agreement": LABEL_B}, True, "owner probe", None)
    again = manage_as_owner("catalyst_member_on_file", ADA, "--nda", LABEL_A, "--user-agreement", LABEL_B,
                            "--completion-verified", "--recorded-by", "someone else")
    assert json.loads(again.stdout)["outcome"] == "unchanged" and "member on file" not in again.stderr
    assert list(MemberAgreementOnFile.objects.values_list("pk", "recorded_by")) == [(row.pk, "owner probe")]  # untouched
    different = run([sys.executable, "manage.py", "catalyst_member_on_file", ADA, "--nda", LABEL_C, "--completion-verified",
                     "--recorded-by", "owner probe"], **owner_env())
    assert different.returncode != 0 and "different_record_needs_correct" in different.stderr
    corrected = json.loads(manage_as_owner("catalyst_member_on_file", ADA, "--nda", LABEL_C, "--completion-verified",
                                           "--recorded-by", "owner probe", "--correct").stdout)
    assert corrected["outcome"] == "corrected" and corrected["covers"] == {"nda": LABEL_C}
    old, new = MemberAgreementOnFile.objects.order_by("id")
    assert old.superseded_at is not None and new.superseded_at is None
    # A concurrent run that commits first is reported as such.
    import applications.members as live_members

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(live_members, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(IntegrityError("dup")))
        with pytest.raises(CommandError, match=r"refused \(concurrent_record\)"):
            call_command("catalyst_member_on_file", ADA, "--nda", LABEL_A, "--completion-verified", "--recorded-by", "x")


def test_9kg_52_a_member_on_file_needs_a_known_address_a_verified_completion_and_plain_labels(privileged_reset):
    invite(privileged_reset.connect("owner", autocommit=True), ADA)
    base = ["--completion-verified", "--recorded-by", "owner probe"]
    refusals = {
        "unknown_member": [BOB, "--nda", LABEL_A, *base],
        "completion_not_verified": [ADA, "--nda", LABEL_A, "--recorded-by", "x"],
        "covers_nothing": [ADA, *base],
        "label_not_a_plain_label": [ADA, "--nda", "https://example.test/agreements/nda.pdf", *base],
        "label_not_a_plain_label ": [ADA, "--nda", "roster/row 12", *base],
        "label_not_a_plain_label  ": [ADA, "--nda", "signed by ada@example.test", *base],
        "label_looks_like_an_identifier": [ADA, "--nda", "NDA 0123456789ABCDEFGHIJ", *base],
        "label_too_long": [ADA, "--nda", "v " * 51, *base],
        "label_empty": [ADA, "--nda", "   ", *base],
        "not_an_email_address": ["not-an-address", "--nda", LABEL_A, *base],
        "recorded_by_empty": [ADA, "--nda", LABEL_A, "--completion-verified", "--recorded-by", " "],
        "recorded_by_too_long": [ADA, "--nda", LABEL_A, "--completion-verified", "--recorded-by", ("abcd " * 13)[:60] + "z"],
        "recorded_by_not_a_plain_label": [ADA, "--nda", LABEL_A, "--completion-verified", "--recorded-by", "owner@example.test"],
    }
    for expected, args in refusals.items():
        refused = run([sys.executable, "manage.py", "catalyst_member_on_file", *args], **owner_env())
        assert refused.returncode != 0 and f"({expected.strip()})" in refused.stderr, (args, refused.stderr)
    assert MemberAgreementOnFile.objects.count() == 0
    # The edges that pass: a 100-character label of short words, a 60-character recorder, a 19-character run.
    label, recorder = ("abcd " * 20)[:99] + "z", ("abcd " * 12)[:59] + "z"
    assert (len(label), len(recorder)) == (100, 60)
    edge = json.loads(manage_as_owner("catalyst_member_on_file", ADA, "--nda", label, "--user-agreement",
                                      "NDA 0123456789ABCDEFGHI", "--completion-verified", "--recorded-by", recorder).stdout)
    assert edge["outcome"] == "recorded" and MemberAgreementOnFile.objects.get().recorded_by == recorder
    assert MemberAgreementOnFile.objects.get().covers == {"nda": label, "user_agreement": "NDA 0123456789ABCDEFGHI"}
    assert members.check_label("  NDA  2 ") == "NDA 2"


def test_9kg_52_the_member_record_is_fixed_by_the_database_for_every_role(privileged_reset):
    invite(privileged_reset.connect("owner", autocommit=True), ADA)
    on_file(ADA, "--nda", LABEL_A)
    on_file(ADA, "--nda", LABEL_B, "--correct")
    old, new = MemberAgreementOnFile.objects.order_by("id")
    with pytest.raises(ProgrammingError, match="permission denied for table applications_memberagreementonfile"):
        MemberAgreementOnFile.objects.create(email_key=BOB, covers={"nda": LABEL_A}, completion_verified=True, recorded_by="web")
    app_role = run([sys.executable, "manage.py", "catalyst_member_on_file", ADA, "--nda", LABEL_C, "--completion-verified",
                    "--recorded-by", "web", "--correct"],
                   CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=conf.CATALYST_DB_ROLES["app"],
                   CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"])
    assert app_role.returncode != 0 and "could not be written (ProgrammingError)" in app_role.stderr
    app_conn = privileged_reset.connect("app", autocommit=True)
    assert app_conn.execute("SELECT count(*) FROM applications_memberagreementonfile").fetchone()[0] == 2
    for sql in ("UPDATE applications_memberagreementonfile SET superseded_at = now() WHERE id = %s",
                "DELETE FROM applications_memberagreementonfile WHERE id = %s"):
        with pytest.raises(psycopg.Error, match="permission denied"):
            app_conn.execute(sql, [new.id])
    owner = privileged_reset.connect("owner", autocommit=True)
    for sql, target in (("UPDATE applications_memberagreementonfile SET covers = '{\"nda\": \"other\"}' WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET recorded_by = 'someone else' WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET completion_verified = false WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET email_key = 'bob@example.test' WHERE id = %s", new.id),
                        ("UPDATE applications_memberagreementonfile SET superseded_at = now() + interval '1 hour' WHERE id = %s", old.id),
                        ("DELETE FROM applications_memberagreementonfile WHERE id = %s", old.id)):
        with pytest.raises(psycopg.Error, match="member on file: (UPDATE|DELETE) refused"):
            owner.execute(sql, [target])
    with pytest.raises(psycopg.Error, match="append-only"):
        owner.execute("TRUNCATE applications_memberagreementonfile")
    for covers, verified, constraint in (('{"nda": "x"}', "false", "member_on_file_completion_verified"),
                                         ("{}", "true", "member_on_file_covers_something")):
        with pytest.raises(psycopg.Error, match=constraint):
            owner.execute("INSERT INTO applications_memberagreementonfile (public_id, email_key, covers, completion_verified,"
                          f" recorded_by) VALUES (gen_random_uuid(), %s, %s::jsonb, {verified}, 'owner')", [BOB, covers])
    assert MemberAgreementOnFile.objects.count() == 2


def test_9kg_52_the_dossier_shows_the_member_on_file_state(privileged_reset, settings):
    closed(settings)
    owner = privileged_reset.connect("owner", autocommit=True)
    invite(owner, ADA, issued_by="the owner")
    app = intake(Client())
    staff = logged_in(make_user(privileged_reset, "dossier-staff"))
    before = staff.get(change_url(app)).content.decode()
    assert "new participant: no first-generation agreement on file; signs the current versions" in before
    assert "issued by the owner; issued before the data notice existed" in before  # this row was inserted bare
    manage_as_owner("catalyst_invite", ADA, "--issued-by", "the owner")
    assert "its mail carried data notice version 1" in staff.get(change_url(app)).content.decode()
    on_file(ADA, "--nda", LABEL_A, "--user-agreement", LABEL_B)
    after = staff.get(change_url(app)).content.decode()
    assert (f"agreement on file, first-generation: nda {LABEL_A}, user_agreement {LABEL_B}; completion verified by the owner"
            " off-system (attested, not read from the provider); recorded by owner probe at ") in after
    assert "corrected from" not in after and str(MemberAgreementOnFile.objects.get().public_id) not in after
    on_file(ADA, "--nda", LABEL_C, "--correct")
    corrected = staff.get(change_url(app)).content.decode()
    assert f"first-generation: nda {LABEL_C};" in corrected and f"corrected from nda {LABEL_A}, user_agreement {LABEL_B}" in corrected
    invite(owner, BOB)  # the state follows the address, not the application
    other = intake(Client(), email=BOB, name="Other Example")  # a name on the scan's fixture list (9kg.40)
    assert members.on_file(other) is None and "new participant" in staff.get(change_url(other)).content.decode()
    assert Application.objects.count() == 2


# --- the agreement path: a covered type is referenced, never issued ----------------------------------------------

def test_9kg_52_a_covered_user_agreement_is_referenced_and_the_uncovered_nda_is_issued(h, monkeypatch):
    app = admitted(h, monkeypatch)
    on_file(app.email_key, "--user-agreement", LABEL_B)
    approve(h)
    activate()
    run_worker()
    app.refresh_from_db()
    assert app.stage == "agreements"
    nda_instance = AgreementInstance.objects.get(application=app, agreement_type__key="nda")
    assert nda_instance.issue_status == "issued"  # the type the record does not cover is issued as usual
    assert not AgreementInstance.objects.filter(application=app, agreement_type__key="user_agreement").exists()
    assert completion.referenced(app) == {"user_agreement": LABEL_B}
    assert completion.next_step(app) == (None, None, "waiting_for_gate")  # the NDA's gate, then a hand-off
    client = Client()
    client.force_login(h.agreement_decider)
    page = client.get(reverse("agreements_staff:agreements", args=[app.public_ref])).content.decode()
    assert (f"First-generation agreement on file, version <bdi>{LABEL_B}</bdi>, referenced; counsel confirms coverage before"
            " launch") in page  # the owner-typed label is isolated (bdi), like every typed value on the screens
    assert "user_agreement &middot; referenced" in page and "nda &middot; instance" in page
    assert "user_agreement &middot; instance" not in page
    assert [i.agreement_type.key for i in completion.live_required_instances(app)] == ["nda"]


def test_9kg_52_a_referenced_nda_is_never_issued_and_an_uncovered_user_agreement_waits_for_the_owner_under_d15(h, monkeypatch):
    """The D-15 backstop refuses a User Agreement without a verified NDA instance, and a referenced NDA has none: the
    advance opens an owner item instead of attempting an insert the database refuses (no attempt is used up)."""
    app = admitted(h, monkeypatch)
    on_file(app.email_key, "--nda", LABEL_A)
    approve(h)
    activate()
    run_worker()
    app.refresh_from_db()
    assert app.stage == "agreements" and not AgreementInstance.objects.filter(application=app).exists()
    assert not h.fake.calls("POST", "/envelope/use")
    assert app.events.filter(kind="agreement_referenced", data__types=["nda"]).exists()
    item = StaffItem.objects.get(application=app, status="open", reason_code=completion.REFERENCE_BLOCKED)
    assert item.dedupe_key == f"advance:{app.public_ref}:user_agreement"
    assert not PendingAction.objects.filter(kind=completion.ADVANCE, subject_id=app.public_ref).exclude(status="done").exists()
    assert not app.events.filter(kind="action_failed").exists()  # refused in code, never by the database
    client = Client()
    client.force_login(h.agreement_decider)
    page = client.get(reverse("agreements_staff:agreements", args=[app.public_ref])).content.decode()
    assert f"First-generation agreement on file, version <bdi>{LABEL_A}</bdi>, referenced" in page and "nda &middot; referenced" in page
    assert "the database (D-15) refuses a User Agreement without a verified NDA" in page
    # Recording the User Agreement as on file too settles it: everything is referenced and the sequence hands off.
    on_file(app.email_key, "--nda", LABEL_A, "--user-agreement", LABEL_B, "--correct")
    completion.enqueue_advance(Application.objects.get(pk=app.pk))
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"
    assert not AgreementInstance.objects.filter(application=app).exists()


def test_9kg_52_a_member_with_every_agreement_on_file_hands_off_without_issuing_anything(h, monkeypatch):
    app = admitted(h, monkeypatch)
    on_file(app.email_key, "--nda", LABEL_A, "--user-agreement", LABEL_B)
    approve(h)
    activate()
    run_worker()
    app.refresh_from_db()
    assert app.stage == "agreements_complete"
    assert not AgreementInstance.objects.filter(application=app).exists() and not h.fake.calls("POST", "/envelope/use")
    refs, digest, reason = completion.prerequisites(app)
    record = str(MemberAgreementOnFile.objects.get().public_id)
    assert reason == "" and refs == {"nda": {"referenced": LABEL_A, "record": record},
                                     "user_agreement": {"referenced": LABEL_B, "record": record}}
    assert completion.live_required_instances(app) == []
    client = Client()
    client.force_login(h.agreement_decider)
    page = client.get(reverse("agreements_staff:agreements", args=[app.public_ref])).content.decode()
    assert page.count("counsel confirms coverage before launch") == 2 and "No agreements yet." not in page
    on_file(app.email_key, "--nda", LABEL_C, "--user-agreement", LABEL_B, "--correct")
    assert completion.prerequisites(Application.objects.get(pk=app.pk))[1] != digest  # a correction changes the digest


# --- the decision: no v2 decline for an existing member (030 Q8) --------------------------------------------------

def decision_form(app, outcome):
    form = {"digest": decisions.decision_state(app)["digest"], "outcome": outcome, "reason_code": "synthetic_reason"}
    for criterion, values in rationale().items():
        form.update({f"cap-{criterion}": values["capability"], f"str-{criterion}": values["evidence_strength"],
                     f"note-{criterion}": values["note"]})
    return form


def test_9kg_52_the_decision_service_refuses_a_decline_for_a_member_on_file(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    on_file(app.email_key, "--nda", LABEL_A)
    with pytest.raises(DecisionRefused, match="decline_refused_member_on_file"):
        decide(d, app, "decline")
    app.refresh_from_db()
    assert app.stage == "awaiting_decision" and not QualificationDecision.objects.filter(application=app).exists()
    decide(d, app, "hold")  # hold stays open to the decision group
    assert Application.objects.get(pk=app.pk).stage == "on_hold"


def test_9kg_52_the_decision_form_offers_no_decline_for_a_member_on_file_and_refuses_a_forged_one(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    client = Client()
    client.force_login(d.decider)
    page_url = reverse("assessments_staff:decision", args=[app.public_ref])
    assert '<option value="decline">' in client.get(page_url).content.decode()  # a new participant may be declined
    on_file(app.email_key, "--nda", LABEL_A)
    page = client.get(page_url).content.decode()
    assert '<option value="decline">' not in page and '<option value="hold">' in page
    assert "no v2 decline for an existing member (council record 030 Q8)" in page
    forged = client.post(reverse("assessments_staff:decide", args=[app.public_ref]), decision_form(app, "decline"), follow=True)
    assert "Refused: decline_refused_member_on_file" in forged.content.decode()
    app.refresh_from_db()
    assert app.stage == "awaiting_decision" and not QualificationDecision.objects.filter(application=app).exists()
