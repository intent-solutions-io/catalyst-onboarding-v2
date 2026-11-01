"""bgl.16: the first-generation import (035). Synthetic only: a first-generation database built in its own schema of
this run's test database (tests/firstgen_v1.py), read by the owner-run command over a real libpq connection.

Proved: a case in every first-generation state lands at its mapped stage with the state kept verbatim, paused, with
nothing queued or sent; a completed NDA and User Agreement become a member-on-file record and confirmed details; an
open envelope is reported, never adopted; a released case keeps its mailbox as a live reservation; outbound
Message-IDs and [CAT-] references associate replies; a dry run leaves nothing; the report's counts are the rows; a
re-run creates nothing; a failed person is reported while the others import; and erasing an imported person clears
everything the import wrote about them.
"""

import json
import os
import sys
from collections import Counter

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from agreements.models import AgreementDetailsVersion
from applications.models import Application, ApplicationEvent, MemberAgreementOnFile, SubmissionVersion
from assessments.models import QualificationDecision
from correspondence.models import ApprovedMessage, OutboundMessage
from firstgen import threads
from firstgen.models import ImportedCase, ImportedRecord, ImportRun
from provisioning.models import AddressReservation, ProvisioningRequest
from tests.firstgen_v1 import V1, new_id
from tests.support import manage_as_owner, run
from tests.test_erasure import decided, erase, owner_scan  # noqa: F401  (decided is a fixture)
from workflow.models import AutomationPause, PendingAction

STAGES = {  # reference: (v1 state, expected v2 stage)
    "CAT-RQ00-0001": ("requested", "submitted"),
    "CAT-RQ00-0002": ("requested", "contact_verified"),
    "CAT-RV00-0003": ("reviewing", "assessing"),
    "CAT-NI00-0004": ("needs_information", "awaiting_answers"),
    "CAT-HD00-0005": ("held", "awaiting_decision"),
    "CAT-LP00-0006": ("lapsed", "awaiting_answers"),
    "CAT-ND00-0007": ("nda_pending", "agreements"),
    "CAT-SP00-0008": ("setup_pending", "agreements"),
    "CAT-RP00-0009": ("release_pending", "agreements_complete"),
    "CAT-PV00-0010": ("provisioning", "provisioning"),
    "CAT-AC00-0011": ("active", "active"),
    "CAT-SU00-0012": ("suspended", "active"),
    "CAT-OF00-0013": ("offboarding", "closed"),
    "CAT-OD00-0014": ("offboarded", "closed"),
    "CAT-WD00-0015": ("withdrawn", "withdrawn"),
    "CAT-DC00-0016": ("declined", "declined"),
}
WANDA = ("Wanda Synthetic", "wanda.synthetic@example.test")  # the withdrawn person the erasure test erases


@pytest.fixture
def v1(privileged_reset):
    db = V1(privileged_reset.connect("owner", autocommit=True))
    try:
        yield db
    finally:
        db.drop()


def populate(v1) -> dict:
    """A first-generation database with a case in every state and every table in use. Returns ids the tests need."""
    ids = {}
    for n, (reference, (state, stage)) in enumerate(STAGES.items()):
        name, email = (WANDA if state == "withdrawn" else (f"Person {reference[-2:]}", f"p{reference[-2:]}@example.test"))
        verified = stage != "submitted"
        case = v1.case(state, name, email, reference=reference, verified=verified, hours=n * 10,
                       revision=state == "withdrawn")
        ids[reference] = case
        v1.event(case, None, "requested", "created", n * 10)
        if state != "requested":
            v1.event(case, "requested", "reviewing", "review_started", n * 10 + 1)
    # Review history and a clarification thread with a reply (needs_information, then lapsed).
    for reference in ("CAT-NI00-0004", "CAT-LP00-0006"):
        case = ids[reference]
        run_id = new_id()
        v1.insert("review_run", id=run_id, case_id=case, stage="decide", input_case_version=2, input_fingerprint="a" * 64,
                  status="succeeded", outcome="write_queued", action="ask_questions", output={"decision": "ask"},
                  model_id="synthetic-model", prompt_pack_version="synthetic-pack", prompt_sha256="b" * 64,
                  input_class="intake", policy_version="synthetic-policy.v1", started_at=v1.at(30))
        v1.insert("review_evidence", id=f"src-{new_id().lower()}", case_id=case, run_id=run_id, kind="public_page",
                  url="https://example.test/work", final_url="https://example.test/work", fetched_at=v1.at(30),
                  sha256="c" * 64, content_type="text/html", byte_count=10, excerpt="A synthetic page")
        draft = new_id()
        v1.insert("review_question", id=f"q-{new_id().lower()}", case_id=case, decide_run_id=run_id,
                  criterion_id="work_example", round=1, status="sent", draft_id=draft, created_at=v1.at(31))
        v1.insert("review_draft", id=draft, case_id=case, decide_run_id=run_id, write_run_id=run_id,
                  body_text="Hello, which part did you build?", question_ids=[], status="queued", created_at=v1.at(31),
                  updated_at=v1.at(31))
        v1.event(case, "reviewing", "needs_information", "information_requested", 32)
        outbound, message_id = v1.outbound(case, "review_clarification", 32)
        ids[f"{reference}:message_id"] = message_id
        inbound = new_id()
        v1.insert("inbound_message", id=inbound, folder="INBOX", uidvalidity=7, uid=100 + len(ids), message_key=new_id() * 2,
                  classification="matched", case_id=case, outbound_message_id=outbound, received_at=v1.at(33),
                  created_at=v1.at(33))
        v1.insert("applicant_message", id=new_id(), case_id=case, direction="out", sent_at=v1.at(32),
                  subject="A question", body_text="Hello, which part did you build?", source_key=new_id() * 2,
                  template="review_clarification", created_at=v1.at(32))
        v1.insert("applicant_message", id=new_id(), case_id=case, direction="in", sent_at=v1.at(33), subject="Re: A question",
                  body_text="I built the planner.", source_key=new_id() * 2, inbound_message_id=inbound,
                  created_at=v1.at(33))
    v1.event(ids["CAT-LP00-0006"], "needs_information", "lapsed", "lapsed", 40)
    # Agreements: an open NDA envelope; an NDA done and the UA open; both done with details (and later states).
    v1.agreement(ids["CAT-ND00-0007"], "nda", "sent", 70)
    v1.job("agreement_sync", "queued", ids["CAT-ND00-0007"], 71)
    v1.agreement(ids["CAT-SP00-0008"], "nda", "completed", 80)
    v1.agreement(ids["CAT-SP00-0008"], "user_agreement", "partially_signed", 81)
    for reference in ("CAT-RP00-0009", "CAT-PV00-0010", "CAT-AC00-0011"):
        case = ids[reference]
        nda = v1.agreement(case, "nda", "durable", 90)
        ua = v1.agreement(case, "user_agreement", "completed", 91)
        v1.insert("agreement_details", id=new_id(), agreement_id=ua, case_id=case, legal_full_name=f"Legal {reference}",
                  residence="US-AL", mailing_address="1 Synthetic Way, Testville, AL 00000, US", phone="+15555550100",
                  captured_at=v1.at(92), field_set="ua_v24", address_line1="1 Synthetic Way", locality="Testville",
                  region="AL", postal_code="00000", country_code="US")
        ids[f"{reference}:ua"], ids[f"{reference}:nda"] = ua, nda
    # Provisioning (approved, not created) and active (released, created, CRM, legacy import, a UA capture).
    v1.insert("mailbox_account", id=new_id(), case_id=ids["CAT-PV00-0010"], domain="members.example.test",
              username="person10", username_source="derived", status="approved", approved_by="policy",
              approved_at=v1.at(95), created_at=v1.at(95), updated_at=v1.at(95))
    active = ids["CAT-AC00-0011"]
    v1.insert("case_release", id=new_id(), case_id=active, released_by="policy", policy_version="synthetic-release.v1",
              nda_agreement_id=ids["CAT-AC00-0011:nda"], ua_agreement_id=ids["CAT-AC00-0011:ua"],
              ua_envelope_id="envelope_ua", archive_basis="archive_source", verified_at=v1.at(96), created_at=v1.at(96))
    v1.insert("mailbox_account", id=new_id(), case_id=active, domain="members.example.test", username="person11",
              username_source="derived", status="created", approved_by="policy", approved_at=v1.at(97),
              created_at_provider=v1.at(97), welcome_sent_at=v1.at(98), created_at=v1.at(97), updated_at=v1.at(98))
    v1.insert("crm_projection", case_id=active, person_id="twenty-person-11", link_method="created", linked_at=v1.at(99),
              note_id="twenty-note-11", projection_version="cpn-projection.v2", created_at=v1.at(99), updated_at=v1.at(99))
    v1.insert("crm_review_item", id=new_id(), case_id=active, kind="field_overwritten", field="city",
              dedupe_key=f"overwritten:{active}", created_at=v1.at(99))
    v1.insert("legacy_agreement_import", agreement_id=ids["CAT-AC00-0011:nda"], case_id=active,
              legacy_envelope_id="legacy-envelope-11", document_label="228 (pre-v1.1)", completed_at=v1.at(90),
              executed_pdf_sha256="d" * 64, verified_status="COMPLETED", signed_recipients=2, verified_at=v1.at(90),
              imported_by="operator", created_at=v1.at(90))
    v1.insert("ua_details_capture", envelope_id="envelope-ua-11", case_id=active, agreement_id=ids["CAT-AC00-0011:ua"],
              outcome="service_details", completed_at=v1.at(91), first_seen_at=v1.at(91), updated_at=v1.at(91))
    # The withdrawn person: a reply in their own words, so the erasure has history to clear.
    wanda = ids["CAT-WD00-0015"]
    v1.insert("applicant_message", id=new_id(), case_id=wanda, direction="in", sent_at=v1.at(151),
              subject="Withdrawing", body_text=f"Please withdraw me. {WANDA[0]}", source_key=new_id() * 2,
              created_at=v1.at(151))
    v1.event(wanda, "reviewing", "withdrawn", "withdrawn", 152, actor="operator", reason="applicant_request")
    v1.event(ids["CAT-DC00-0016"], "reviewing", "declined", "declined", 162, actor="operator", reason="not_a_fit")
    # Rows of no case: an owner notice, an unmatched reply, a capture for someone outside the service, the cursor.
    v1.outbound(None, "owner_reply_notice", 200)
    v1.insert("inbound_message", id=new_id(), folder="INBOX", uidvalidity=7, uid=900, message_key=new_id() * 2,
              classification="unmatched", needs_review=True, received_at=v1.at(200), created_at=v1.at(200))
    v1.insert("ua_details_capture", envelope_id="envelope-outside", outcome="written", signer_email_sha256="e" * 64,
              display_name="Olga Outside", mailing_address="9 Outside Road", completed_at=v1.at(201),
              first_seen_at=v1.at(201), updated_at=v1.at(201))
    v1.insert("mailbox_cursor", folder="INBOX", uidvalidity=7, last_uid=900, last_checked_at=v1.at(202))
    # Operational rows: finished jobs and the rate counter.
    for _ in range(5):
        v1.job("review.decide", "succeeded")
    v1.insert("intake_rate_event", bucket="f" * 64, created_at=v1.at(1))
    return ids


def import_v1(v1, *extra, check=True):
    args = [sys.executable, "manage.py", "catalyst_import_v1", "--source-dsn", v1.dsn, "--run-by", "owner probe", *extra]
    if check:
        result = manage_as_owner(*args[2:])
    else:
        from django.conf import settings
        from django.db import connection

        result = run(args, CATALYST_DB_NAME=connection.settings_dict["NAME"],
                     CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                     CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
    return result, json.loads(result.stdout) if result.stdout.strip() else None


# --- the dry run and the report ---------------------------------------------------------------------------------------

def test_bgl16_a_dry_run_reports_every_row_and_leaves_nothing(v1):
    populate(v1)
    result, report = import_v1(v1, "--dry-run")
    assert report["dry_run"] is True and report["failures"] == [] and report["personal_rows_dropped_without_reason"] == 0
    for table, inserted in v1.counts.items():
        if table == "agreement_acceptance":
            continue
        row = report["tables"][table]
        assert row["read"] == inserted, table
        assert row["mapped"] + row["already_imported"] + sum(row["skipped"].values()) == inserted, table
        assert row["unaccounted"] == 0, table
    assert report["tables"]["job"]["skipped"] == {"operational_not_imported": v1.counts["job"]}
    assert report["tables"]["intake_rate_event"]["skipped"] == {"operational_not_imported": 1}
    created = report["created"]
    assert created["applications.Application"] == len(STAGES) == created["firstgen.ImportedCase"]
    assert created["applications.SubmissionVersion"] == len(STAGES) + 1  # the withdrawn person's revision
    assert created["assessments.QualificationDecision"] == 1 and created["agreements.AgreementDetailsVersion"] == 3
    assert report["jobs"]["queued_in_v2"] == 0 and report["jobs"]["open_or_failed_for_cases"] == {"agreement_sync/queued": 1}
    # Nothing was written: every v2 table the run reported is empty again.
    for model in (Application, SubmissionVersion, ImportedCase, ImportedRecord, ImportRun, AutomationPause,
                  MemberAgreementOnFile, AgreementDetailsVersion, AddressReservation, QualificationDecision):
        assert not model.objects.exists(), model
    # The report names no person: no name, no address.
    assert WANDA[0] not in result.stdout and WANDA[1] not in result.stdout and "@example.test" not in result.stdout


# --- the real run ---------------------------------------------------------------------------------------------------

def test_bgl16_every_v1_state_maps_to_its_stage_is_paused_and_nothing_is_queued_or_sent(v1):
    populate(v1)
    _, report = import_v1(v1)
    assert report["failures"] == [] and ImportRun.objects.count() == 1
    for reference, (state, stage) in STAGES.items():
        imported = ImportedCase.objects.select_related("application").get(reference=reference)
        assert (imported.v1_state, imported.mapped_stage, imported.application.stage) == (state, stage, stage), reference
        open_stage = stage not in ("withdrawn", "declined", "closed")
        assert AutomationPause.objects.filter(subject_id=imported.application.public_ref).exists() == open_stage, reference
        assert ApplicationEvent.objects.filter(application=imported.application, kind="imported_first_generation").count() == 1
    assert ImportedCase.objects.get(reference="CAT-LP00-0006").v1_resume_state == "needs_information"
    assert "v1_held_maps_to_awaiting_decision" in ImportedCase.objects.get(reference="CAT-HD00-0005").findings
    assert not PendingAction.objects.exists()  # nothing queued, so nothing can be sent
    assert not OutboundMessage.objects.exists() and not ApprovedMessage.objects.exists()
    # The submission holds the first-generation answers under the form-fields keys.
    fields = SubmissionVersion.objects.get(application__first_generation__reference="CAT-AC00-0011", version_number=1).submitted_fields
    assert (fields["residence_country"], fields["phone_e164"], fields["interest_track"], fields["marketing_wording_version"],
            fields["age_attested"], fields["verification_wording_version"]) == (
        "US", "+15555550100", "cert_and_work", "marketing-updates.v1", True, "credential-verification.v1")
    assert fields["education"] == [{"institution": "Example University", "credential": "bachelor, Synthetic Studies"}]
    assert fields["claims"]["credentials"][0]["url"] == "https://example.test/cert/1"
    assert fields["first_generation"]["reference"] == "CAT-AC00-0011"
    unverified = Application.objects.get(first_generation__reference="CAT-RQ00-0001")
    assert unverified.contact_verified_at is None and not unverified.adoptions.exists()
    assert Application.objects.get(first_generation__reference="CAT-AC00-0011").adoptions.count() == 1
    # Each in-flight case says what it needs; the import queued none of it.
    needs = {f["reference"]: f["needs"] for f in report["followups"]}
    assert any(n.startswith("agreements:") for n in needs["CAT-ND00-0007"])
    assert any(n.startswith("v1_jobs_not_carried: agreement_sync/queued") for n in needs["CAT-ND00-0007"])
    assert "CAT-WD00-0015" not in needs and "CAT-DC00-0016" not in needs
    # The timeline keeps its original times.
    events = ImportedRecord.objects.filter(application__first_generation__reference="CAT-WD00-0015", kind="case_event")
    assert events.count() == 3 and events.order_by("occurred_at").first().occurred_at.year == 2026


def test_bgl16_agreements_details_mailboxes_crm_and_the_decline(v1):
    ids = populate(v1)
    import_v1(v1)
    covers = {row.email_key: row.covers for row in MemberAgreementOnFile.objects.all()}
    assert covers["p08@example.test"] == {"nda": "v1.1 (first generation)"}  # the UA is still open
    for n in ("09", "10", "11"):
        assert covers[f"p{n}@example.test"] == {"nda": "v1.1 (first generation)", "user_agreement": "v2.4 (first generation)"}
    assert "p07@example.test" not in covers  # an open envelope is not a completed agreement
    assert "open_v1_envelope:nda" in ImportedCase.objects.get(reference="CAT-ND00-0007").findings
    details = AgreementDetailsVersion.objects.get(application__first_generation__reference="CAT-RP00-0009")
    assert (details.status, details.agreement_type.key, details.values["legal_full_name"], details.values["country_code"]) == (
        "confirmed", "user_agreement", "Legal CAT-RP00-0009", "US")
    record = ImportedRecord.objects.get(v1_table="agreement_details", target__endswith=str(details.public_id))
    assert "legal_full_name" not in record.data  # kept once, in the v2 record
    active = AddressReservation.objects.get(local_part="person11")
    assert active.released_at is None and active.basis == "reviewed_exception"
    assert ProvisioningRequest.objects.get(reservation=active).status == "active"
    pending = ProvisioningRequest.objects.get(reservation__local_part="person10")
    assert pending.status == "failed_needs_staff"
    assert "v1_mailbox_approved_not_created_check_mxroute" in ImportedCase.objects.get(reference="CAT-PV00-0010").findings
    imported = ImportedCase.objects.get(reference="CAT-AC00-0011")
    assert (imported.crm_person_id, imported.crm_note_id) == ("twenty-person-11", "twenty-note-11")
    # bgl.14 (parity integration): the Twenty projection's own lookup reads this record, so the imported application
    # continues the first generation's person and note (crm.projection.imported, not a stand-in)
    from crm import projection

    origin = projection.imported(imported.application)
    assert (origin.case_id, origin.reference, origin.person_id, origin.note_id) == (
        imported.v1_case_id, "CAT-AC00-0011", "twenty-person-11", "twenty-note-11")
    assert origin.requested_at == imported.v1_created_at
    kinds = Counter(ImportedRecord.objects.filter(application=imported.application).values_list("kind", flat=True))
    for kind in ("case_release", "crm_projection", "crm_review_item", "legacy_agreement_import", "ua_details_capture",
                 "agreement", "mailbox_account"):
        assert kinds[kind] >= 1, kind
    decision = QualificationDecision.objects.get(application__first_generation__reference="CAT-DC00-0016")
    assert (decision.outcome, decision.basis, decision.reason_code, decision.run) == ("decline", "human_only", "not_a_fit", None)
    # The capture of a person outside the service keeps no personal column.
    outside = ImportedRecord.objects.get(v1_table="ua_details_capture", v1_id="envelope-outside")
    assert outside.application is None and not {"display_name", "mailing_address", "signer_email_sha256"} & set(outside.data)
    assert ids  # the fixture ids were built


def test_bgl16_replies_to_first_generation_threads_associate_by_message_id_and_reference(v1):
    ids = populate(v1)
    import_v1(v1)
    asked = Application.objects.get(first_generation__reference="CAT-NI00-0004")
    message_id = ids["CAT-NI00-0004:message_id"]
    assert threads.application_for_message_ids(["<unknown@example.test>", message_id]) == asked.pk
    assert threads.application_for_message_ids(["<unknown@example.test>"]) is None
    both = [message_id, ids["CAT-LP00-0006:message_id"]]
    assert threads.application_for_message_ids(both) is None  # two applications: ambiguous, never guessed
    assert threads.application_for_subject("Re: A question about your request [CAT-NI00-0004]") == asked.pk
    assert threads.application_for_subject("Re: no reference") is None
    # bgl.6 (parity integration): with this app installed, the reply path's resolver is this module, and association
    # reaches the imported application through it, by Message-ID and then by the subject reference
    from types import SimpleNamespace

    from django.conf import settings

    from correspondence import association

    assert settings.CATALYST_FOREIGN_THREAD_RESOLVER == "firstgen.threads" and association.foreign_resolver() is threads
    reply = SimpleNamespace(is_bounce=False, in_reply_to=[message_id], references=[], embedded_message_ids=[], subject="Re: x")
    assert association.foreign_application_id(reply) == asked.pk
    by_subject = SimpleNamespace(is_bounce=False, in_reply_to=["<unknown@example.test>"], references=[],
                                 embedded_message_ids=[], subject="Re: A question about your request [CAT-NI00-0004]")
    assert association.foreign_application_id(by_subject) == asked.pk
    bounce = SimpleNamespace(is_bounce=True, in_reply_to=[], references=[], embedded_message_ids=["<unknown@example.test>"],
                             subject="Undelivered [CAT-NI00-0004]")
    assert association.foreign_application_id(bounce) is None  # a bounce never matches by subject (C0)
    record = ImportedRecord.objects.get(v1_table="outbound_message", message_id=message_id)
    assert record.application_id == asked.pk
    replies = ImportedRecord.objects.filter(application=asked, kind="message").values_list("data", flat=True)
    assert {r["direction"] for r in replies} == {"in", "out"}
    notice = ImportedRecord.objects.get(v1_table="outbound_message", data__template="owner_reply_notice")
    assert notice.application is None and notice.message_id


# --- idempotency and failure ----------------------------------------------------------------------------------------

def test_bgl16_a_second_run_creates_nothing_and_a_late_row_is_added_once(v1):
    ids = populate(v1)
    _, first = import_v1(v1)
    counts = {m: m.objects.count() for m in (Application, SubmissionVersion, ImportedCase, ImportedRecord,
                                            MemberAgreementOnFile, AgreementDetailsVersion, AddressReservation)}
    _, second = import_v1(v1)
    assert second["created"] == {} and second["failures"] == []
    assert {m: m.objects.count() for m in counts} == counts
    for table, row in second["tables"].items():
        if table not in ("job", "intake_rate_event"):
            assert row["mapped"] == 0 and row["already_imported"] + sum(row["skipped"].values()) == row["read"], table
    v1.event(ids["CAT-AC00-0011"], "active", "active", "cohort_assigned", 300, actor="operator")
    _, third = import_v1(v1)
    assert third["created"] == {"firstgen.ImportedRecord": 1} and ImportedRecord.objects.count() == counts[ImportedRecord] + 1
    assert ImportRun.objects.count() == 3 and first["run"] != second["run"]


def test_bgl16_a_failed_person_is_reported_and_everyone_else_is_imported(v1, privileged_reset):
    populate(v1)
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("INSERT INTO applications_application (public_ref, email, email_key, display_name, stage,"
                  " next_version_number) VALUES (gen_random_uuid(), 'p03@example.test', 'p03@example.test', 'Native',"
                  " 'submitted', 1)")
    v1.case("closed", "Person 99", "p99@example.test", reference="CAT-XX00-0099", credentials=False)  # not a v1 state
    v1.insert("case_event", case_id="NO-SUCH-CASE", subject="case", to_state="reviewing", event="x", actor="worker",
              created_at=v1.at(1))
    result, report = import_v1(v1, check=False)
    assert result.returncode == 1 and "2 case(s) failed" in result.stderr
    assert {(f["reference"], f["error"]) for f in report["failures"]} == {
        ("CAT-RV00-0003", "open_v2_application_exists"), ("CAT-XX00-0099", "unknown_v1_state:closed")}
    assert report["tables"]["case_event"]["skipped"]["orphan_case"] == 1
    assert report["tables"]["intake_request"]["skipped"] == {"case_failed:open_v2_application_exists": 1,
                                                             "case_failed:unknown_v1_state:closed": 1}
    assert report["personal_rows_dropped_without_reason"] == 0
    assert ImportedCase.objects.count() == len(STAGES) - 1
    assert not ImportedCase.objects.filter(reference__in=("CAT-RV00-0003", "CAT-XX00-0099")).exists()


def test_bgl16_the_command_runs_only_as_the_owner_and_never_schedules_followups(v1):
    with pytest.raises(CommandError, match="not_the_owner"):
        call_command("catalyst_import_v1", "--source-dsn", v1.dsn, "--run-by", "probe")
    with pytest.raises(CommandError, match="followups_need_staff"):
        call_command("catalyst_import_v1", "--source-dsn", v1.dsn, "--run-by", "probe", "--schedule-followups")
    result, _ = import_v1(v1, "--source-dsn", "host=127.0.0.1 port=1 dbname=none user=none password=secret-probe",
                          check=False)
    assert result.returncode != 0 and "source_unreadable" in result.stderr and "secret-probe" not in result.stderr


# --- erasure ------------------------------------------------------------------------------------------------------

def test_bgl16_erasing_an_imported_person_clears_everything_the_import_wrote(v1, privileged_reset, decided):  # noqa: F811
    populate(v1)
    import_v1(v1)
    app = Application.objects.get(first_generation__reference="CAT-WD00-0015")
    owner = privileged_reset.connect("owner", autocommit=True)
    markers = (WANDA[0], WANDA[1], "Wanda")
    before = owner_scan(owner, *markers)
    assert any(key.startswith("firstgen_importedrecord:") for key in before), before
    assert len(before) >= 4, before
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.status == "erased"
    assert owner_scan(owner, *markers) == {}
    erased = Application.objects.get(pk=app.pk)
    assert erased.email_key == f"erased:{app.public_ref}" and erased.stage == "withdrawn"
    assert all(r.data == {} for r in ImportedRecord.objects.filter(application=app))
    assert ImportedCase.objects.get(application=app).reference == "CAT-WD00-0015"  # provenance stays, nothing personal
