"""bgl.14 (034 rows 42 and 43): the Twenty projection, the applicant file note and the daily User Agreement details fill,
behind CATALYST_TWENTY_PROJECTION.

Everything runs against the local stub (`tests/twenty_stub.py`): synthetic people, notes and token only. The actions are
driven through the ledger (`workflow.ledger.run_one`) with the two Twenty handlers, inside the test's transaction; the
erasure case commits through its own connections (the privileged reset).
"""

from datetime import date
from types import SimpleNamespace

import pytest
from django.db.models.functions import Now

from agreements.models import AgreementDetailsVersion, AgreementType
from applications import staff as application_staff
from applications.models import Application, ApplicationEvent, SubmissionVersion
from config import guards
from correspondence import processing
from correspondence.models import StaffItem
from crm import mapping, projection, twenty
from crm.models import TwentyLink
from erasure import record, service
from tests.test_erasure import decided, erase, subject  # noqa: F401  (fixture and helpers)
from tests.test_inbound import tls  # noqa: F401  (fixture)
from tests.twenty_stub import TOKEN, TwentyStub
from workflow import ledger
from workflow.models import PendingAction

REGISTRY = {projection.PROJECT: projection.ProjectApplication(), projection.FILL: projection.FillDetails()}


@pytest.fixture
def tw(tls, settings):  # noqa: F811
    stub = TwentyStub(tls.twenty).start()
    settings.CATALYST_TWENTY_PROJECTION = True
    settings.CATALYST_TWENTY_URL = f"https://twenty.example.test:{stub.port}"
    settings.CATALYST_TWENTY_ADDRESS = "127.0.0.1"
    settings.CATALYST_TWENTY_CA_FILE = tls.ca
    settings.CATALYST_TWENTY_TOKEN = TOKEN
    settings.CATALYST_TWENTY_DEADLINE_SECONDS = 2
    settings.CATALYST_TWENTY_ATTEMPTS = 3
    settings.CATALYST_WORKER_RETRY_SECONDS = 0  # a retry is due at once, so the test drains it
    yield stub
    stub.stop()


def application(email="ada@example.test", name="Ada Example Lovelace", stage="submitted", **fields):
    app = Application.objects.create(email=email, email_key=email.strip().lower(), display_name=name, stage=stage)
    SubmissionVersion.objects.create(application=app, version_number=1, origin="form", submitted_fields={
        "name": name, "email": email, "reason": "I build synthetic onboarding tools.", **fields})
    return app


def event(app, kind="synthetic_step"):
    return ApplicationEvent.objects.create(application=app, kind=kind, actor_type="system", data={})


def drain(limit=40):
    for _ in range(limit):
        if not ledger.run_one(REGISTRY):
            return
    raise AssertionError("the ledger did not drain")


def actions(kind=projection.PROJECT):
    return PendingAction.objects.filter(kind=kind)


def items(app, reason=None):
    found = StaffItem.objects.filter(application=app, status="open", reason_code__startswith="twenty_")
    return found.filter(reason_code=reason) if reason else found


def details(app, **values):
    row = AgreementDetailsVersion.objects.create(
        application=app, agreement_type=AgreementType.objects.get(key="user_agreement"), version=1, values=values,
        values_sha256="0" * 64, recorded_by="user:1")
    AgreementDetailsVersion.objects.filter(pk=row.pk).update(status="confirmed", confirmed_by="user:2", confirmed_at=Now())
    return row


# --- the switch ------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl14_with_the_switch_off_nothing_is_queued_and_a_queued_action_calls_nothing(tw, settings):
    settings.CATALYST_TWENTY_PROJECTION = False
    app = application()
    event(app)
    assert not actions().exists() and not projection.schedule_details_fill()
    settings.CATALYST_TWENTY_PROJECTION = True
    event(app)  # queued while on, then switched off before it runs
    settings.CATALYST_TWENTY_PROJECTION = False
    drain()
    assert actions().get().status == "done" and actions().get().last_error == "projection_off"
    assert tw.requests == []


# --- create, fields, note ----------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl14_an_event_creates_the_person_with_the_first_generation_fields_and_one_applicant_file(tw):
    app = application(stage="agreements", interest_track="cert_and_work", marketing_opt_in=True,
                      marketing_wording_version="marketing-updates.v1", phone_e164="+15550100",
                      claims={"work": [{"url": "https://www.linkedin.com/in/ada-synthetic", "note": ""},
                                       {"url": "https://example.test/portfolio", "note": ""}]})
    event(app)
    event(app)  # a burst coalesces into one queued projection
    assert actions().count() == 1
    drain()
    (person,) = tw.people.values()
    assert person["cpnCaseId"] == str(app.public_ref) and person["cpnCaseState"] == "NDA_PENDING"
    assert person["cpnNextAction"] == "AWAIT_NDA_SIGNATURE" and person["cpnException"] is False
    assert person["cpnInterestTrack"] == "CERT_AND_WORK" and person["cpnLeadSource"] == "CATALYST_REQUEST_ACCESS"
    assert person["cpnWorkLinks"] == "https://example.test/portfolio"
    assert person["linkedinLink"]["primaryLinkUrl"] == "https://www.linkedin.com/in/ada-synthetic"
    assert person["cpnMarketingOptIn"] is True and person["cpnMarketingOptInSource"] == "request_form:marketing-updates.v1"
    assert person["name"] == {"firstName": "Ada Example", "lastName": "Lovelace"}
    assert person["emails"]["primaryEmail"] == "ada@example.test"
    assert person["cpnProjectionVersion"] == mapping.PROJECTION_VERSION and "cpnRequestedAt" in person
    assert not mapping.LEGACY_FIELDS & set(person)
    (note,) = tw.notes_of(person["id"])
    assert note["title"] == "Applicant file — Ada Example Lovelace"
    assert mapping.marker(str(app.public_ref)) in note["bodyV2"]["markdown"]
    assert "I build synthetic onboarding tools." in note["bodyV2"]["markdown"]
    link = TwentyLink.objects.get(application=app)
    assert (link.person_id, link.note_id, link.link_method) == (person["id"], note["id"], "created")
    assert set(link.field_hashes) >= {"cpnCaseId", "cpnCaseState"} and len(link.note_sha256) == 64
    assert {r["authorization"] for r in tw.requests} == {f"Bearer {TOKEN}"}
    assert all(TOKEN not in (a.last_error or "") for a in PendingAction.objects.all())
    # Nothing changed: the next projection reads and writes nothing.
    before = len(tw.writes())
    event(app)
    drain()
    assert len(tw.writes()) == before and len(tw.people) == 1 and len(tw.notes) == 1


@pytest.mark.django_db
def test_bgl14_the_note_is_created_once_and_then_updated_in_place(tw):
    app = application()
    event(app)
    drain()
    (note_id,) = tw.notes
    Application.objects.filter(pk=app.pk).update(stage="withdrawn")
    event(app, "withdrawn")
    drain()
    assert list(tw.notes) == [note_id] and len(tw.calls("POST", "/rest/notes")) == 1
    assert len(tw.calls("PATCH", f"/rest/notes/{note_id}")) == 1 and "Case state: WITHDRAWN" in tw.notes[note_id]["bodyV2"]["markdown"]
    assert len(tw.calls("POST", "/rest/noteTargets")) == 1  # attached once
    (person,) = tw.people.values()
    assert person["cpnCaseState"] == "WITHDRAWN"
    # A note someone wrote by hand on the same person is never touched.
    own = tw.add_note("Applicant file — Ada Example Lovelace", "my own observations", person["id"])
    Application.objects.filter(pk=app.pk).update(stage="closed")
    event(app, "closed")
    drain()
    assert tw.notes[own]["bodyV2"]["markdown"] == "my own observations"


# --- matching ---------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl14_the_stored_person_id_is_used_first(tw):
    app = application()
    chosen = tw.add_person("someone-else@example.test", cpnCaseId="")
    tw.add_person("ada@example.test")  # would match by email
    TwentyLink.objects.create(application=app, person_id=chosen, link_method="staff")
    event(app)
    drain()
    assert tw.people[chosen]["cpnCaseId"] == str(app.public_ref)
    assert not tw.calls("POST", "/rest/people") and len(tw.people) == 2


@pytest.mark.django_db
def test_bgl14_an_email_match_is_exact_after_trim_and_case_fold_and_never_fuzzy(tw):
    tw.add_person("Grace@Example.TEST")  # same address, other case: a match
    lookalike = tw.add_person("xada@example.test", additional=["ada@example.test.evil"])  # never a match
    app = application(email=" grace@example.test")
    event(app)
    other = application(email="ada@example.test", name="Ada Other")
    event(other)
    drain()
    grace = TwentyLink.objects.get(application=app)
    assert grace.link_method == "email_match" and tw.people[grace.person_id]["emails"]["primaryEmail"] == "Grace@Example.TEST"
    ada = TwentyLink.objects.get(application=other)
    assert ada.link_method == "created" and ada.person_id != lookalike and "cpnCaseId" not in tw.people[lookalike]
    # An additional email matches too.
    third = tw.add_person("primary@example.test", additional=["hopper@example.test"])
    hopper = application(email="Hopper@example.test", name="Grace Hopper")
    event(hopper)
    drain()
    assert TwentyLink.objects.get(application=hopper).person_id == third


@pytest.mark.django_db
def test_bgl14_several_matches_open_one_staff_item_and_write_nothing(tw):
    tw.add_person("ada@example.test")
    tw.add_person("ADA@example.test")
    app = application()
    event(app)
    drain()
    event(app)
    drain()
    assert tw.writes() == [] and items(app, "twenty_ambiguous_match").count() == 1
    assert not TwentyLink.objects.get(application=app).person_id


@pytest.mark.django_db
def test_bgl14_a_person_linked_to_another_open_application_is_not_taken(tw):
    first = application()
    event(first)
    drain()
    Application.objects.filter(pk=first.pk).update(email_key="other@example.test")  # its person keeps the address
    second = application()
    event(second)
    drain()
    assert items(second, "twenty_person_linked_elsewhere").count() == 1 and len(tw.people) == 1


# --- idempotency under retry -------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl14_a_lost_reply_is_recovered_by_reading_and_nothing_is_duplicated(tw, settings):
    settings.CATALYST_TWENTY_ATTEMPTS = 5
    tw.fault("POST /rest/people", "lost")
    tw.fault("POST /rest/notes", "lost")
    tw.fault("POST /rest/noteTargets", "lost")
    app = application()
    event(app)
    drain()
    assert len(tw.people) == 1 and len(tw.notes) == 1 and len(tw.targets) == 1
    assert len(tw.calls("POST", "/rest/people")) == 1 and len(tw.calls("POST", "/rest/notes")) == 1
    link = TwentyLink.objects.get(application=app)
    assert link.link_method == "recovered" and link.note_id == next(iter(tw.notes))
    action = actions().get()
    assert action.status == "done" and action.attempts == 4  # three lost replies, each found again by the next read
    assert items(app).count() == 0


@pytest.mark.django_db
def test_bgl14_an_outage_is_retried_within_the_bound_and_the_last_failure_opens_one_item(tw):
    tw.fault("GET /rest/people", *[503] * 6)
    app = application()
    event(app)
    drain()
    # The last failure opens the item, whose own event queues one more projection; that one fails too, and the item is
    # already open, so nothing queues a third: an outage is bounded.
    assert [(a.status, a.attempts, a.last_error) for a in actions().order_by("id")] == [("failed", 3, "http_503")] * 2
    assert items(app, "twenty_projection_failed").count() == 1 and tw.people == {}


@pytest.mark.django_db
def test_bgl14_a_refusal_opens_one_item_and_is_not_retried(tw):
    tw.fault("POST /rest/people", 400)
    app = application()
    event(app)
    drain()
    action = actions().filter(status="failed").get()
    assert action.attempts == 1 and action.last_error == "http_400"
    assert items(app, "twenty_request_rejected").count() == 1


# --- conflicts -------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl14_a_field_edited_in_twenty_opens_one_item_and_is_overwritten(tw):
    app = application()
    event(app)
    drain()
    (person_id,) = tw.people
    tw.people[person_id]["cpnCaseState"] = "ACTIVE"  # a person changed an owned field by hand
    event(app)
    drain()
    assert tw.people[person_id]["cpnCaseState"] == "REQUESTED"
    assert items(app, "twenty_field_overwritten").count() == 1
    (item,) = items(app, "twenty_field_overwritten")
    assert "cpnCaseState" in item.dedupe_key and "ACTIVE" not in item.dedupe_key  # a digest, never the value
    event(app)
    drain()
    assert items(app, "twenty_field_overwritten").count() == 1  # the same edit is not raised again
    assert set(projection.REVIEW_REASONS) <= processing.ACKNOWLEDGE_ONLY
    assert set(projection.REVIEW_REASONS) <= set(application_staff.REASONS)


# --- the User Agreement details --------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl14_the_daily_fill_writes_only_blank_details_and_never_overwrites(tw):
    blank = application(email="blank@example.test", name="Blank Person")
    partial = application(email="partial@example.test", name="Partial Person")
    conflict = application(email="conflict@example.test", name="Conflict Person")
    for app in (blank, partial, conflict):
        event(app)
    drain()
    ids = {a.pk: TwentyLink.objects.get(application=a).person_id for a in (blank, partial, conflict)}
    tw.people[ids[blank.pk]]["mailingAddress"] = {}
    tw.people[ids[partial.pk]]["mailingAddress"] = {"addressStreet1": "1 Synthetic Way", "addressCity": ""}
    tw.people[ids[conflict.pk]]["mailingAddress"] = {"addressStreet1": "9 Other Road"}
    tw.people[ids[conflict.pk]]["name"] = {"firstName": "Someone", "lastName": "Else"}
    values = {"legal_full_name": "Legal Synthetic Name", "phone": "+15550199", "address_line1": "1 Synthetic Way",
              "locality": "Testville", "postal_code": "00000", "country_code": "us", "residence": "US"}
    for app in (blank, partial, conflict):
        details(app, **values)
    before = len(tw.calls("PATCH", "/rest/people"))
    assert projection.schedule_details_fill() and not projection.schedule_details_fill()  # one queued at a time
    drain()
    b, p, c = (tw.people[ids[a.pk]] for a in (blank, partial, conflict))
    assert b["mailingAddress"]["addressStreet1"] == "1 Synthetic Way" and b["mailingAddress"]["addressCountry"] == "US"
    assert b["phones"]["primaryPhoneNumber"] == "+15550199" and c["phones"]["primaryPhoneNumber"] == "+15550199"
    assert b["name"] == {"firstName": "Blank", "lastName": "Person"}  # the intake name is there: never overwritten
    assert p["mailingAddress"]["addressCity"] == "Testville" and p["mailingAddress"]["addressStreet1"] == "1 Synthetic Way"
    assert c["mailingAddress"] == {"addressStreet1": "9 Other Road"} and c["name"] == {"firstName": "Someone", "lastName": "Else"}
    assert len(tw.calls("PATCH", "/rest/people")) - before == 3  # blank and partial filled; conflict: phone only
    fill = actions(projection.FILL).get(idempotency_key=f"{projection.FILL}:1")
    assert fill.status == "done" and actions(projection.FILL).filter(status="queued").count() == 1  # tomorrow's
    # A second run finds nothing blank left and writes nothing.
    PendingAction.objects.filter(kind=projection.FILL, status="queued").update(due_at=Now())
    before = len(tw.writes())
    drain()
    assert len(tw.writes()) == before


@pytest.mark.django_db
def test_bgl14_details_never_overwrite_a_name_the_intake_wrote(tw):
    app = application(name="Intake Name")
    event(app)
    drain()
    details(app, legal_full_name="Legal Other Name")
    event(app)
    drain()
    (person,) = tw.people.values()
    assert person["name"] == {"firstName": "Intake", "lastName": "Name"}  # filled at create, so not blank: kept


# --- imported applications --------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl14_an_imported_application_continues_its_first_generation_person_and_note(tw, monkeypatch):
    v1_case = "01JSYNTHETICCASE0000000000"
    person = tw.add_person("ada@example.test", cpnCaseId=v1_case, cpnCaseState="NDA_PENDING")
    tw.add_person("ada@example.test")  # an email match would be ambiguous: the recorded id is used instead
    note = tw.add_note("Applicant file — Ada Example Lovelace", f"old text\n\ncase {v1_case}, applicant-file.v2", person)
    app = application(stage="agreements")
    monkeypatch.setattr(projection, "imported", lambda a: projection.Imported(
        v1_case, "CAT-SYNT-0001", person, note, app.created_at) if a.pk == app.pk else None)
    event(app)
    drain()
    link = TwentyLink.objects.get(application=app)
    assert (link.person_id, link.note_id, link.link_method) == (person, note, "imported")
    assert tw.people[person]["cpnCaseId"] == v1_case and tw.people[person]["cpnCaseRef"] == "CAT-SYNT-0001"
    assert "cpnLeadSource" not in tw.people[person]  # the first generation's lead source is left as it is
    assert len(tw.people) == 2 and len(tw.notes) == 1 and not tw.calls("POST")
    assert mapping.marker(v1_case) in tw.notes[note]["bodyV2"]["markdown"] and items(app).count() == 0


# --- erasure ---------------------------------------------------------------------------------------------------------

def test_bgl14_an_erased_person_owes_the_twenty_handoff_and_the_link_keeps_no_digest(privileged_reset, decided):  # noqa: F811
    app = subject()
    TwentyLink.objects.create(application=app, person_id="synthetic-person", note_id="synthetic-note",
                              field_hashes={"cpnCaseId": "a" * 64}, link_method="created")
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.status == "erased" and "twenty" in outcome.handoffs
    link = TwentyLink.objects.get(application=app)
    assert link.field_hashes == {} and link.person_id == "synthetic-person"  # the owner deletes it at Twenty by this id
    head = service.handoff(str(app.public_ref), "twenty", date.today().isoformat())
    assert record.verify(head)["handoffs_outstanding"] == len(outcome.handoffs) - 1
    # No projection runs for an erased person, even with the switch on.
    assert app.pk and Application.objects.get(pk=app.pk).email_key.startswith("erased:")


@pytest.mark.django_db
def test_bgl14_an_erased_application_is_never_projected(tw):
    app = application()
    Application.objects.filter(pk=app.pk).update(email_key=f"erased:{app.public_ref}", stage="withdrawn")
    event(app)
    drain()
    assert tw.requests == [] and actions().get().last_error == "nothing_to_project"


# --- guards and the client --------------------------------------------------------------------------------------------

def _twenty_settings(environment, **values):
    base = {"CATALYST_ENV": environment, "CATALYST_PROCESS_ROLE": "worker", "CATALYST_TWENTY_PROJECTION": False,
            "CATALYST_TWENTY_URL": "", "CATALYST_TWENTY_ADDRESS": "", "CATALYST_TWENTY_CA_FILE": "",
            "CATALYST_TWENTY_TOKEN": ""}
    return SimpleNamespace(**{**base, **values})


def test_bgl14_the_guards_refuse_live_twenty_settings_outside_test_and_staging():
    live = {"CATALYST_TWENTY_PROJECTION": True, "CATALYST_TWENTY_URL": "https://twenty.example.test",
            "CATALYST_TWENTY_ADDRESS": "127.0.0.1", "CATALYST_TWENTY_CA_FILE": "/synthetic/ca.pem",
            "CATALYST_TWENTY_TOKEN": "x"}
    for environment in ("test", "staging"):
        assert guards.twenty_problems(_twenty_settings(environment, **live), {}, "worker") == []
    for environment in ("production", "development"):
        assert guards.twenty_problems(_twenty_settings(environment), {}, "worker") == []  # off and empty: fine
        for name, value in live.items():
            problems = guards.twenty_problems(_twenty_settings(environment, **{name: value}), {}, "worker")
            assert problems == [f"{name} is allowed only in the test and staging environments until the Twenty swap"]
    for change, words in ((("CATALYST_TWENTY_URL", "http://twenty.example.test"), "must be https"),
                          (("CATALYST_TWENTY_URL", "https://crm.synthetic.example"), "must name a .test host"),
                          (("CATALYST_TWENTY_ADDRESS", "192.0.2.10"), "literal loopback address"),
                          (("CATALYST_TWENTY_CA_FILE", ""), "never the system store")):
        problems = guards.twenty_problems(_twenty_settings("test", **{**live, change[0]: change[1]}), {}, "worker")
        assert any(words in p for p in problems), (change, problems)
    for name in guards.TWENTY_TEST_ONLY:
        assert guards.twenty_problems(_twenty_settings("test"), {name: "x"}, "worker") == [
            f"{name} may not be set from the environment"]
    assert guards.twenty_problems(_twenty_settings("test", CATALYST_TWENTY_TOKEN="x"), {}, "web")
    assert guards.twenty_problems(_twenty_settings("test", CATALYST_TWENTY_TOKEN="x", CATALYST_PROCESS_ROLE="fetcher"), {}, "worker")
    assert "CATALYST_TWENTY_TOKEN" in guards.SECRET_ENV_NAMES  # a secret file outside test and development
    assert "TWENTY_" in guards.PROVIDER_ENV_PREFIXES  # the first generation's variables stay refused


def test_bgl14_the_shipped_settings_keep_the_projection_off_and_empty():
    from django.conf import settings

    assert settings.CATALYST_TWENTY_PROJECTION is False
    assert settings.CATALYST_TWENTY_URL == settings.CATALYST_TWENTY_ADDRESS == settings.CATALYST_TWENTY_CA_FILE == ""


@pytest.mark.django_db
def test_bgl14_the_client_refuses_an_unpinned_or_unconfigured_target_before_sending(tw, settings):
    settings.CATALYST_TWENTY_ADDRESS = "192.0.2.10"
    with pytest.raises(twenty.TwentyError) as refused:
        twenty.get_person("synthetic")
    assert refused.value.code == "twenty_address_not_pinned" and not refused.value.sent
    settings.CATALYST_TWENTY_TOKEN = ""
    with pytest.raises(twenty.TwentyError, match="twenty_not_configured"):
        twenty.get_person("synthetic")
    assert tw.requests == []
    settings.CATALYST_TWENTY_TOKEN, settings.CATALYST_TWENTY_ADDRESS = TOKEN, "127.0.0.1"
    with pytest.raises(twenty.TwentyError, match="filter_value_refused"):
        twenty.find_people_by_field("cpnCaseId", 'x"]')
    assert TOKEN not in repr(twenty.TwentyError("http_500", sent=True, status=500))
