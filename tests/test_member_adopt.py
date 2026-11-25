"""dy7.5: attaching existing first-generation members to v2 as active member cases (owner decision 211.7.6, 2026-11-21).

Synthetic only: a first-generation database built in its own schema (tests/firstgen_v1.py) holding one imported case
and completed User Agreement captures of people outside any case, imported by `catalyst_import_v1`, then the owner-run
`catalyst_member_adopt` over a private input file written to the test's temporary directory. Every person, address,
envelope id and mailbox name is invented.

Proved: an accepted entry becomes an active, paused application with one adoption event, the member-on-file record
and, for an existing mailbox, a live reservation with an active checklist request; nothing is queued or sent and the
import records are untouched; a re-run reports unchanged and creates nothing; a dry run writes nothing and sees the
same refusals; every refusal is a code and leaves nothing behind; the output and the log carry no address, name or
envelope id; the adopted cases are on the staff screens and in the health counts; and erasing an adopted person clears
everything the adoption wrote about them.
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from agreements.models import AgreementInstance, AgreementTemplateVersion, AgreementType
from applications.models import Application, ApplicationEvent, MemberAgreementOnFile
from config import system_health
from correspondence.models import ApprovedMessage, OutboundMessage
from firstgen import adoption
from firstgen.models import ImportedRecord
from provisioning.models import AddressReservation, ProvisioningRequest
from tests.firstgen_v1 import V1
from tests.support import manage_as_owner, run
from tests.test_erasure import decided, erase, owner_scan  # noqa: F401  (decided is a fixture)
from tests.test_outbound import staff
from workflow.models import AutomationPause, PendingAction

DOMAIN = "members.example.test"
CASEY = (
    "Casey Imported",
    "casey.imported@example.test",
)  # a first-generation case: known to v2 after the import
ZEPH = ("Zephyrine Adoptee", "zephyrine.adoptee@example.test", "zephyrine")
QUILL = ("Quillon Adoptee", "quillon.adoptee@example.test")
OUTSIDE = (
    "envelope-outside-zeph",
    "envelope-outside-quill",
    "envelope-outside-third",
    "envelope-outside-fourth",
)
RECORDER = "owner probe"


@pytest.fixture
def v1(privileged_reset):
    db = V1(privileged_reset.connect("owner", autocommit=True))
    try:
        yield db
    finally:
        db.drop()


@pytest.fixture
def snapshot(v1):
    """One imported active case with its own completed User Agreement capture, and four completed User Agreement
    captures outside any case (the pilot signers), as the first generation stored them."""
    case = v1.case("active", CASEY[0], CASEY[1], reference="CAT-AC00-0001", hours=0)
    v1.event(case, None, "requested", "created", 0)
    nda = v1.agreement(case, "nda", "durable", 2)
    ua = v1.agreement(case, "user_agreement", "completed", 3)
    v1.insert(
        "ua_details_capture",
        envelope_id="envelope-of-the-case",
        case_id=case,
        agreement_id=ua,
        outcome="service_details",
        completed_at=v1.at(4),
        first_seen_at=v1.at(4),
        updated_at=v1.at(4),
    )
    for n, envelope in enumerate(OUTSIDE):
        v1.insert(
            "ua_details_capture",
            envelope_id=envelope,
            outcome="written",
            signer_email_sha256=f"{n}" * 64,
            display_name=f"Outside Person {n}",
            mailing_address=f"{n} Outside Road",
            completed_at=v1.at(10 + n),
            first_seen_at=v1.at(10 + n),
            updated_at=v1.at(10 + n),
        )
    manage_as_owner(
        "catalyst_import_v1", "--source-dsn", v1.dsn, "--run-by", "owner probe"
    )
    assert ImportedRecord.objects.filter(
        v1_table="ua_details_capture", application__isnull=True
    ).count() == len(OUTSIDE)
    return SimpleNamespace(
        case_nda=f"envelope_{nda.lower()}", case_ua=f"envelope_{ua.lower()}"
    )


def entry(name=ZEPH[0], email=ZEPH[1], envelope=OUTSIDE[0], **extra):
    return {
        "email": email,
        "display_name": name,
        "user_agreement_envelope_id": envelope,
        "user_agreement_version": "ua-v2.4",
        **extra,
    }


def zeph(**extra):
    fields = {
        "nda_envelope_id": "nda-envelope-zeph",
        "nda_version": "nda-v1.1",
        "mailbox_local_part": ZEPH[2],
        **extra,
    }
    email = fields.pop("email", ZEPH[1])
    return entry(email=email, **fields)


def write(tmp_path, entries, name="members.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"members": entries}))
    return str(path)


def adopt(path, *extra, recorder=RECORDER, domain=DOMAIN):
    """The command as the owner, whatever its exit status. Returns (process, report or None)."""
    from django.conf import settings
    from django.db import connection

    args = ["catalyst_member_adopt", "--input", path, "--recorded-by", recorder, *extra]
    if domain is not None:
        args += ["--mailbox-domain", domain]
    result = run(
        [sys.executable, "manage.py", *args],
        CATALYST_DB_NAME=connection.settings_dict["NAME"],
        CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
        CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"],
    )
    return result, json.loads(result.stdout) if result.stdout.strip() else None


def imported_records():
    return sorted(
        ImportedRecord.objects.values_list(
            "pk", "v1_table", "v1_id", "application_id", "data", "target"
        )
    )


def assert_private(result, *values):
    text = (result.stdout + result.stderr).lower()
    for value in values:
        assert value.lower() not in text, value


# --- the happy path -----------------------------------------------------------------------------------------------


def test_dy7_5_an_existing_member_becomes_an_active_paused_case_with_agreements_on_file_and_mailbox_reserved(
    snapshot, tmp_path
):
    before = imported_records()
    pauses_before = system_health.aged_waits_health()["pauses"]["waiting"]
    result, report = adopt(
        write(tmp_path, [zeph(), entry(*QUILL, envelope=OUTSIDE[1])])
    )
    assert result.returncode == 0, result.stderr
    assert report["dry_run"] is False and report["counts"] == {
        "adopted": 2,
        "unchanged": 0,
        "refused": 0,
    }
    assert report["queued"] == 0 and report["sent"] == 0 and report["refusals"] == {}
    assert report["created"] == {
        "applications.Application": 2,
        "applications.ApplicationEvent": 2,
        "applications.MemberAgreementOnFile": 2,
        "provisioning.AddressReservation": 1,
        "provisioning.ProvisioningRequest": 1,
        "workflow.AutomationPause": 2,
    }
    assert [e["index"] for e in report["entries"]] == [0, 1]
    app = Application.objects.get(email_key=ZEPH[1])
    assert report["entries"][0] == {
        "index": 0,
        "outcome": "adopted",
        "public_ref": str(app.public_ref),
        "reference": app.reference,
    }
    assert (app.stage, app.display_name, app.contact_verified_at) == (
        "active",
        ZEPH[0],
        None,
    )
    assert app.reference.startswith("CAT-") and not app.versions.exists()
    # One adoption event, linking the import record that proved the envelope.
    event = ApplicationEvent.objects.get(application=app)
    proof = ImportedRecord.objects.get(v1_table="ua_details_capture", v1_id=OUTSIDE[0])
    assert (event.kind, event.actor_type, event.actor_ref) == (
        adoption.EVENT,
        "system",
        adoption.ACTOR,
    )
    assert event.data["ua_record"] == proof.pk and event.data["recorded_by"] == RECORDER
    assert (
        event.data["ua_version"],
        event.data["nda_version"],
        event.data["nda_record"],
    ) == ("ua-v2.4", "nda-v1.1", None)
    # Agreements on file: nobody is asked to sign again.
    on_file = MemberAgreementOnFile.objects.get(
        email_key=ZEPH[1], superseded_at__isnull=True
    )
    assert (on_file.covers, on_file.recorded_by) == (
        {"nda": "nda-v1.1", "user_agreement": "ua-v2.4"},
        RECORDER,
    )
    assert MemberAgreementOnFile.objects.get(email_key=QUILL[1]).covers == {
        "user_agreement": "ua-v2.4"
    }
    # Nothing automatic: a system pause on each.
    for person in (app, Application.objects.get(email_key=QUILL[1])):
        pause = AutomationPause.objects.get(
            subject_type="application", subject_id=person.public_ref
        )
        assert pause.actor_ref == adoption.ACTOR
    # The existing mailbox: a live reservation and an active checklist request, so v2 never reserves or creates it.
    reservation = AddressReservation.objects.get(application=app)
    assert (
        reservation.local_part,
        reservation.domain,
        reservation.basis,
        reservation.released_at,
    ) == (ZEPH[2], DOMAIN, "reviewed_exception", None)
    request = ProvisioningRequest.objects.get(application=app)
    assert (
        request.reservation_id,
        request.method,
        request.status,
        request.approved_by,
    ) == (reservation.pk, "checklist", "active", f"owner:{RECORDER}")
    assert not AddressReservation.objects.filter(
        application__email_key=QUILL[1]
    ).exists()
    # Nothing queued, nothing sent, the import records untouched.
    assert not PendingAction.objects.exists()
    assert not OutboundMessage.objects.exists() and not ApprovedMessage.objects.exists()
    assert imported_records() == before
    # No address, name or envelope id in the output or the log; the log names the recorder.
    assert_private(
        result,
        ZEPH[0],
        ZEPH[1],
        QUILL[0],
        QUILL[1],
        OUTSIDE[0],
        OUTSIDE[1],
        "nda-envelope-zeph",
        "@",
    )
    assert f"by {RECORDER}: 2 adopted, 0 unchanged, 0 refused" in result.stderr
    # The health counts see the two new pauses, as they see the import's.
    assert system_health.aged_waits_health()["pauses"]["waiting"] == pauses_before + 2


def test_dy7_5_adopted_members_are_listed_on_the_staff_screens(
    snapshot, tmp_path, privileged_reset
):
    result, _ = adopt(write(tmp_path, [zeph()]))
    assert result.returncode == 0, result.stderr
    app = Application.objects.get(email_key=ZEPH[1])
    viewer = staff(SimpleNamespace(committed=privileged_reset), "adoption-viewer")
    privileged_reset.connect("owner", autocommit=True).execute(
        "INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission",
        [viewer.pk],
    )
    browser = Client()
    browser.force_login(viewer)
    listing = browser.get(
        reverse("correspondence_staff:applications"), {"show": "paused"}
    )
    assert listing.status_code == 200
    page = listing.content.decode()
    assert ZEPH[0] in page and str(app.public_ref) in page
    for path in (
        reverse("correspondence_staff:application", args=[app.public_ref]),
        reverse("provisioning_staff:provisioning", args=[app.public_ref]),
        reverse("agreements_staff:agreements", args=[app.public_ref]),
    ):
        assert browser.get(path).status_code == 200, path


# --- idempotence and the dry run ----------------------------------------------------------------------------------


def test_dy7_5_a_re_run_reports_unchanged_and_creates_nothing_and_a_different_entry_is_refused(
    snapshot, tmp_path
):
    path = write(tmp_path, [zeph(), entry(*QUILL, envelope=OUTSIDE[1])])
    assert adopt(path)[0].returncode == 0
    rows = (
        Application.objects.count(),
        ApplicationEvent.objects.count(),
        MemberAgreementOnFile.objects.count(),
        AutomationPause.objects.count(),
        AddressReservation.objects.count(),
        ProvisioningRequest.objects.count(),
    )
    result, report = adopt(path, recorder="someone else")
    assert result.returncode == 0, result.stderr
    assert (
        report["counts"] == {"adopted": 0, "unchanged": 2, "refused": 0}
        and report["created"] == {}
    )
    assert report["entries"][0]["public_ref"] == str(
        Application.objects.get(email_key=ZEPH[1]).public_ref
    )
    assert (
        Application.objects.count(),
        ApplicationEvent.objects.count(),
        MemberAgreementOnFile.objects.count(),
        AutomationPause.objects.count(),
        AddressReservation.objects.count(),
        ProvisioningRequest.objects.count(),
    ) == rows
    # The address typed differently is the same person; a changed entry for them is refused, never applied.
    result, report = adopt(
        write(
            tmp_path,
            [zeph(email=ZEPH[1].upper()), zeph(nda_version="nda-v2.0")],
            "again.json",
        )
    )
    assert result.returncode == 1
    assert [e["outcome"] for e in report["entries"]] == ["unchanged", "refused"]
    assert report["entries"][1]["code"] == "adopted_with_different_input"
    assert (
        MemberAgreementOnFile.objects.get(email_key=ZEPH[1]).covers["nda"] == "nda-v1.1"
    )


def test_dy7_5_a_dry_run_writes_nothing_and_sees_the_refusals_a_real_run_sees(
    snapshot, tmp_path
):
    before = (
        Application.objects.count(),
        ApplicationEvent.objects.count(),
        MemberAgreementOnFile.objects.count(),
        AutomationPause.objects.count(),
        AddressReservation.objects.count(),
        ProvisioningRequest.objects.count(),
    )
    records = imported_records()
    # The second entry repeats the first person differently: refused, because the first, earlier in the same run,
    # adopted them.
    path = write(
        tmp_path,
        [
            zeph(),
            entry(ZEPH[0], ZEPH[1], OUTSIDE[1]),
            entry(*QUILL, envelope=OUTSIDE[1]),
        ],
    )
    dry, dry_report = adopt(path, "--dry-run")
    assert dry.returncode == 1 and dry_report["dry_run"] is True
    assert dry_report["counts"] == {"adopted": 2, "unchanged": 0, "refused": 1}
    assert dry_report["refusals"] == {"adopted_with_different_input": 1}
    assert "dry run by owner probe" in dry.stderr
    assert (
        Application.objects.count(),
        ApplicationEvent.objects.count(),
        MemberAgreementOnFile.objects.count(),
        AutomationPause.objects.count(),
        AddressReservation.objects.count(),
        ProvisioningRequest.objects.count(),
    ) == before
    assert imported_records() == records and not PendingAction.objects.exists()
    real, real_report = adopt(path)
    assert real.returncode == 1
    assert [(e["outcome"], e.get("code")) for e in real_report["entries"]] == [
        (e["outcome"], e.get("code")) for e in dry_report["entries"]
    ]
    assert real_report["created"] == dry_report["created"]


# --- refusals -----------------------------------------------------------------------------------------------------


def test_dy7_5_every_refusal_is_a_code_and_leaves_nothing_behind(
    snapshot, tmp_path, privileged_reset
):
    owner = privileged_reset.connect("owner", autocommit=True)
    # An address invited in v2 with a different agreement record on file: the adoption's record is refused and the
    # application it began is rolled back with it.
    invited = "invited.member@example.test"
    owner.execute(
        "INSERT INTO applications_invitation (public_id, email_key, issued_by, note, issued_at, expires_at)"
        " VALUES (gen_random_uuid(), %s, 'test owner', '', now(), now() + interval '1 day')",
        [invited],
    )
    manage_as_owner(
        "catalyst_member_on_file",
        invited,
        "--nda",
        "nda-v0.9",
        "--completion-verified",
        "--recorded-by",
        "owner probe",
    )
    # An envelope v2 already holds as an agreement instance of a case.
    casey = Application.objects.get(email_key=CASEY[1])
    version = AgreementTemplateVersion.objects.create(
        agreement_type=AgreementType.objects.get(key="nda"),
        version=99,
        provider_template_ref="tmpl-99",
        provider_template_number=99,
        recipient_slots={"SIGNER:1": 1},
        pdf_sha256="0" * 64,
    )
    owner.execute(
        "UPDATE agreements_agreementtemplateversion SET status = 'approved', approved_by = 'test owner',"
        " approved_at = now() WHERE id = %s",
        [version.pk],
    )
    instance = AgreementInstance.objects.create(
        application=casey,
        agreement_type=version.agreement_type,
        template_version=version,
        external_key="onb-synthetic-99",
    )
    AgreementInstance.objects.filter(pk=instance.pk).update(envelope_id=OUTSIDE[3])
    cases = [  # (entry, expected code); entry 0 is adopted first, so the later ones can collide with it
        (zeph(), None),
        ("not an object", "entry_not_an_object"),
        (
            {
                **entry(email="x1@example.test", envelope=OUTSIDE[1]),
                "phone": "+15555550100",
            },
            "unknown_field",
        ),
        (
            {k: v for k, v in entry(email="x2@example.test").items() if k != "email"},
            "missing_email",
        ),
        (entry(name="  ", email="x3@example.test"), "missing_display_name"),
        (
            {
                k: v
                for k, v in entry(email="x4@example.test").items()
                if k != "user_agreement_envelope_id"
            },
            "missing_user_agreement_envelope_id",
        ),
        (
            entry(email="x5@example.test", user_agreement_version=""),
            "missing_user_agreement_version",
        ),
        (entry(email="not-an-address"), "not_an_email_address"),
        (entry(email="x6@example.test", display_name=12), "display_name_not_text"),
        (entry(name="n" * 201, email="x7@example.test"), "display_name_too_long"),
        (
            entry(email="x8@example.test", envelope="../envelope"),
            "user_agreement_envelope_id_malformed",
        ),
        (
            entry(
                email="x9@example.test",
                user_agreement_version="https://example.test/ua.pdf",
            ),
            "user_agreement_version_label_not_a_plain_label",
        ),
        (
            entry(email="x10@example.test", nda_envelope_id="nda env"),
            "nda_envelope_id_malformed",
        ),
        (
            entry(email="x11@example.test", nda_envelope_id="nda-envelope-x11"),
            "missing_nda_version",
        ),
        (
            entry(
                email="x12@example.test",
                envelope=OUTSIDE[1],
                nda_envelope_id=OUTSIDE[1],
                nda_version="nda-v1.1",
            ),
            "nda_envelope_is_the_user_agreement",
        ),
        (
            entry(email="x13@example.test", mailbox_local_part="bad..name"),
            "mailbox_name_not_reservable",
        ),
        (entry(*CASEY, envelope=OUTSIDE[1]), "address_known_to_v2"),
        (
            entry(email="x14@example.test", envelope="envelope-nobody-saw"),
            "envelope_not_in_first_generation_snapshot",
        ),
        (
            entry(email="x15@example.test", envelope="envelope-of-the-case"),
            "envelope_attached_to_a_case",
        ),
        (
            entry(email="x16@example.test", envelope=snapshot.case_ua),
            "envelope_attached_to_a_case",
        ),
        (
            entry(email="x17@example.test", envelope=OUTSIDE[3]),
            "envelope_owned_by_a_v2_case",
        ),
        (
            entry(email="x18@example.test", envelope=OUTSIDE[0]),
            "envelope_already_adopted",
        ),
        (
            entry(
                email="x19@example.test",
                envelope=OUTSIDE[1],
                nda_envelope_id=snapshot.case_nda,
                nda_version="nda-v1.1",
            ),
            "nda_envelope_attached_to_a_case",
        ),
        (
            entry(
                email="x20@example.test",
                envelope=OUTSIDE[1],
                nda_envelope_id="nda-envelope-zeph",
                nda_version="nda-v1.1",
            ),
            "nda_envelope_already_adopted",
        ),
        (
            entry(
                email="x21@example.test",
                envelope=OUTSIDE[1],
                mailbox_local_part=ZEPH[2].upper(),
            ),
            "mailbox_already_reserved",
        ),
        (
            entry(name="Ada Other", email=invited, envelope=OUTSIDE[2]),
            "member_on_file_different_record_needs_correct",
        ),
        (
            entry(
                name=CASEY[0].upper(),
                email="other-casey@example.test",
                envelope=OUTSIDE[2],
            ),
            "name_matches_existing_case_needs_review",
        ),
    ]
    before = imported_records()
    result, report = adopt(write(tmp_path, [raw for raw, _ in cases]))
    assert result.returncode == 1 and "entries refused" in result.stderr
    got = [(e["outcome"], e.get("code")) for e in report["entries"]]
    assert got == [("adopted", None)] + [("refused", code) for _, code in cases[1:]], (
        got
    )
    assert report["counts"] == {"adopted": 1, "unchanged": 0, "refused": len(cases) - 1}
    # Only the first person was written; every refused entry left nothing.
    assert list(
        Application.objects.exclude(email_key=CASEY[1]).values_list(
            "email_key", flat=True
        )
    ) == [ZEPH[1]]
    assert MemberAgreementOnFile.objects.get(email_key=invited).covers == {
        "nda": "nda-v0.9"
    }
    assert (
        AddressReservation.objects.count() == 1 and not PendingAction.objects.exists()
    )
    assert imported_records() == before
    assert_private(
        result,
        ZEPH[1],
        CASEY[1],
        invited,
        "x1@",
        OUTSIDE[0],
        OUTSIDE[3],
        snapshot.case_ua,
        "@",
    )
    # Without a mailbox domain a mailbox entry is refused, and a mailbox-less entry still goes through.
    result, report = adopt(
        write(
            tmp_path,
            [
                entry(*QUILL, envelope=OUTSIDE[1], mailbox_local_part="quillon"),
                entry(*QUILL, envelope=OUTSIDE[1]),
            ],
            "nodomain.json",
        ),
        domain="",
    )
    assert [(e["outcome"], e.get("code")) for e in report["entries"]] == [
        ("refused", "mailbox_domain_not_configured"),
        ("adopted", None),
    ]


def test_dy7_5_the_command_refuses_a_bad_input_file_a_bad_recorder_and_any_login_but_the_owner(
    snapshot, tmp_path
):
    with pytest.raises(CommandError, match="not_the_owner"):
        call_command(
            "catalyst_member_adopt",
            "--input",
            write(tmp_path, [zeph()]),
            "--recorded-by",
            RECORDER,
        )
    secret = tmp_path / "broken.json"
    secret.write_text('{"members": [{"email": "leak.probe@example.test", ')
    bad_files = {
        "input_unreadable": str(tmp_path / "missing.json"),
        "input_unreadable ": str(secret),
        "input_not_a_member_list": str(tmp_path / "list.json"),
        "input_empty": write(tmp_path, [], "empty.json"),
    }
    (tmp_path / "list.json").write_text(json.dumps([zeph()]))
    for code, path in bad_files.items():
        result, report = adopt(path)
        assert (
            result.returncode != 0
            and f"({code.strip()})" in result.stderr
            and report is None
        ), (code, result.stderr)
        assert_private(result, "leak.probe")
    result, _ = adopt(write(tmp_path, [zeph()]), recorder="owner@example.test")
    assert result.returncode != 0 and "(recorded_by_not_a_plain_label)" in result.stderr
    assert not Application.objects.filter(email_key=ZEPH[1]).exists()
    # Standard input works as the file.
    import subprocess

    from django.conf import settings
    from django.db import connection

    from tests.support import ROOT, child_env

    piped = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "catalyst_member_adopt",
            "--input",
            "-",
            "--recorded-by",
            RECORDER,
            "--mailbox-domain",
            DOMAIN,
            "--dry-run",
        ],
        cwd=ROOT,
        input=json.dumps({"members": [zeph()]}),
        capture_output=True,
        text=True,
        timeout=60,
        env=child_env(
            CATALYST_DB_NAME=connection.settings_dict["NAME"],
            CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
            CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"],
        ),
    )
    assert piped.returncode == 0, piped.stderr
    assert (
        json.loads(piped.stdout)["counts"]["adopted"] == 1
        and not Application.objects.filter(email_key=ZEPH[1]).exists()
    )


def test_dy7_5_parse_checks_each_entry_without_the_database():
    parsed = adoption.parse(
        {
            **zeph(),
            "email": "  Zephyrine.Adoptee@Example.TEST ",
            "mailbox_local_part": "Zephyrine",
        }
    )
    assert (parsed.key, parsed.local_part, parsed.nda_version) == (
        ZEPH[1],
        ZEPH[2],
        "nda-v1.1",
    )
    assert (
        parsed.digest(DOMAIN)
        == adoption.parse(zeph()).digest(DOMAIN)
        != adoption.parse(zeph()).digest("other.test")
    )
    assert adoption.parse(entry()).covers() == {
        "nda": None,
        "user_agreement": "ua-v2.4",
    }
    for raw, code in (
        ([], "entry_not_an_object"),
        ({**entry(), "email": 5}, "email_not_text"),
        (entry(email="a" * 330 + "@example.test"), "address_too_long"),
        (
            entry(user_agreement_version="NDA 0123456789ABCDEFGHIJ"),
            "user_agreement_version_label_looks_like_an_identifier",
        ),
    ):
        with pytest.raises(adoption.Refused, match=f"^{code}$"):
            adoption.parse(raw)


# --- erasure ------------------------------------------------------------------------------------------------------


def test_dy7_5_erasing_an_adopted_member_clears_everything_the_adoption_wrote(
    snapshot, tmp_path, privileged_reset, decided
):  # noqa: F811
    result, _ = adopt(write(tmp_path, [zeph()]))
    assert result.returncode == 0, result.stderr
    app = Application.objects.get(email_key=ZEPH[1])
    owner = privileged_reset.connect("owner", autocommit=True)
    markers = (ZEPH[0], ZEPH[1], ZEPH[2])
    before = owner_scan(owner, *markers)
    assert {key.split(":")[0] for key in before} >= {
        "applications_application",
        "applications_memberagreementonfile",
        "provisioning_addressreservation",
    }, before
    owner.execute(
        "UPDATE applications_application SET stage = 'closed' WHERE id = %s", [app.pk]
    )  # erasure needs it
    assert erase(privileged_reset, app.public_ref).status == "erased"
    assert owner_scan(owner, *markers) == {}
    assert ApplicationEvent.objects.get(application=app, kind=adoption.EVENT).data == {}
    assert AutomationPause.objects.filter(
        subject_id=app.public_ref
    ).exists()  # a restriction kept is safe
