"""The first-generation form fields on the v2 request form (parity track 034 rows 3 and 12; bead catalyst-v2-bgl.3).

What the first-generation form collected and v2 did not: country of residence, phone with its calling code, the
interest track, the optional marketing consent, the 18+ attestation, education rows or a "none" tick, certification
rows (a name and an identifier or link) or a "none" tick, and the verification consent. Each answer is stored in the
versioned submission with the S1 fields, shown on the dossier, and tombstoned by the erasure with the rest.

Posts go through the real view as the application role (tests/test_intake.py helpers); the dossier and erasure
tests commit (`privileged_reset`) because the admin and the erasure function read committed rows as other roles.
"""

import pytest

from applications import countries
from applications.forms import (
    ANSWER_TEXT_MAX, CERTIFICATION_SLOTS, EDUCATION_SLOTS, MARKETING_WORDING_VERSION, PHONE_TYPED_MAX,
    VERIFICATION_WORDING_VERSION, AccessRequestForm,
)
from applications.models import Application, SubmissionVersion
from tests import support
from tests.test_erasure import decided, erase, owner_scan  # noqa: F401  (fixture and helpers)
from tests.test_intake import EMPTY, VALID, counts, post
from tests.test_staff import change_url, logged_in, make_user
from workflow.models import PendingAction

# Rows in place of the "none" ticks: one education entry and one certification with an identifier.
ROWS = {"edu_institution_1": "Synthetic Institute", "edu_credential_1": "BSc Computing", "no_degree": "",
        "cred_name_1": "Synthetic Practitioner", "cred_issuer_1": "Synthetic Board", "cred_identifier_1": "SP-0001",
        "no_certifications": ""}


# --- storage --------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_parity_form_a_valid_submission_stores_every_answer(client):
    response = post(client, marketing_opt_in="on", **ROWS, edu_institution_2="Second College", edu_credential_2="Diploma",
                    cred_name_2="Second Cert", cred_url_2="https://verify.example.test/c2")
    assert response.status_code == 302
    version = SubmissionVersion.objects.get()
    assert version.submitted_fields == {
        "name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access.",
        "residence_country": "GB", "phone_e164": "+442079460958", "phone_country": "GB", "interest_track": "cert_only",
        "marketing_opt_in": True, "marketing_wording_version": MARKETING_WORDING_VERSION, "age_attested": True,
        "education": [{"institution": "Synthetic Institute", "credential": "BSc Computing"},
                      {"institution": "Second College", "credential": "Diploma"}],
        "no_degree": False, "no_certifications": False,
        "verification_consent": True, "verification_wording_version": VERIFICATION_WORDING_VERSION,
        "claims": {"work": [], "contribution": "", "experience": "", "confidential": False, "confidential_description": "",
                   "credentials": [{"name": "Synthetic Practitioner", "issuer": "Synthetic Board", "identifier": "SP-0001", "url": ""},
                                   {"name": "Second Cert", "issuer": "", "identifier": "", "url": "https://verify.example.test/c2"}]},
    }
    assert (MARKETING_WORDING_VERSION, VERIFICATION_WORDING_VERSION) == ("marketing-updates.v1", "credential-verification.v1")


@pytest.mark.django_db
def test_parity_form_the_none_ticks_stand_in_for_rows_and_keep_the_s1_shape(client):
    assert post(client).status_code == 302  # VALID ticks both "none" boxes and leaves marketing unticked
    fields = SubmissionVersion.objects.get().submitted_fields
    expected = {k: v for k, v in VALID.items() if k in ("name", "email", "reason")}
    assert fields == {**expected, **support.STORED_ANSWERS}  # no "claims": an S1-shaped submission with the answers
    assert fields["education"] == [] and fields["marketing_opt_in"] is False and "claims" not in fields


# --- refusals: every one is a form error and records nothing -------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize(("fields", "errors"), [
    ({"edu_institution_1": "X", "edu_credential_1": "Y"}, {"no_degree"}),  # rows and the tick together
    ({"no_degree": ""}, {"no_degree"}),  # neither rows nor the tick
    ({"edu_institution_1": "X", "no_degree": ""}, {"edu_credential_1"}),  # a half-filled row
    ({"edu_credential_1": "Y", "no_degree": ""}, {"edu_institution_1"}),
    ({"cred_name_1": "C", "cred_identifier_1": "1"}, {"no_certifications"}),  # rows and the tick together
    ({"no_certifications": ""}, {"no_certifications"}),  # neither
    ({"cred_name_1": "C", "no_certifications": ""}, {"cred_identifier_1"}),  # a name without an identifier or a link
    ({"cred_identifier_1": "1", "no_certifications": ""}, {"cred_name_1"}),  # an identifier without a name
    ({"cred_name_4": "C", "cred_url_4": "http://verify.example.test/c", "no_certifications": ""}, {"cred_url_4"}),  # not https
], ids=["edu-both", "edu-neither", "edu-half-a", "edu-half-b", "cert-both", "cert-neither", "cert-no-ref", "cert-no-name",
        "cert-http"])
def test_parity_form_none_ticks_versus_rows(client, fields, errors):
    response = post(client, **fields)
    assert response.status_code == 200
    assert errors <= set(response.context["form"].errors), response.context["form"].errors
    assert counts() == EMPTY


@pytest.mark.django_db
@pytest.mark.parametrize(("fields", "errors"), [
    ({"edu_institution_1": "i" * (ANSWER_TEXT_MAX + 1), "edu_credential_1": "Y", "no_degree": ""}, {"edu_institution_1"}),
    ({"edu_institution_1": "X", "edu_credential_1": "c" * (ANSWER_TEXT_MAX + 1), "no_degree": ""}, {"edu_credential_1"}),
    ({"phone": "+44 " + "2" * (PHONE_TYPED_MAX - 3)}, {"phone"}),  # too long as typed
    ({"phone": "+44 2079 4609 5812 34"}, {"phone"}),  # 16 digits: past E.164
    ({"phone": "+44 20"}, {"phone"}),  # too short
    ({"phone": "+33 1 23 45 67 89"}, {"phone"}),  # another country's calling code
    ({"phone": "020 7946 0958", "phone_country": "DE"}, {"phone"}),  # a national number outside the North American plan
    ({"phone": "call me"}, {"phone"}),
    ({"phone": ""}, {"phone"}),
    ({"residence_country": "ZZ"}, {"residence_country"}),
    ({"residence_country": "gb"}, {"residence_country"}),  # the code, exactly
    ({"residence_country": ""}, {"residence_country"}),
    ({"phone_country": "ZZ"}, {"phone_country"}),
    ({"interest_track": "work_only"}, {"interest_track"}),
    ({"interest_track": ""}, {"interest_track"}),
    ({"age_attested": ""}, {"age_attested"}),
    ({"verification_consent": ""}, {"verification_consent"}),
], ids=["long-institution", "long-credential", "long-phone-typed", "phone-16-digits", "phone-short", "phone-other-country",
        "phone-national-elsewhere", "phone-letters", "no-phone", "bad-country", "lowercase-country", "no-country",
        "bad-phone-country", "bad-track", "no-track", "no-age", "no-consent"])
def test_parity_form_each_limit_is_refused_and_records_nothing(client, fields, errors):
    response = post(client, **fields)
    assert response.status_code == 200
    assert errors <= set(response.context["form"].errors), response.context["form"].errors
    assert counts() == EMPTY


def test_parity_form_the_row_counts_and_text_limits_are_the_first_generation_ones():
    assert (len(EDUCATION_SLOTS), len(CERTIFICATION_SLOTS), ANSWER_TEXT_MAX) == (3, 4, 150)
    form = AccessRequestForm()
    assert {f for f in form.fields if f.startswith("edu_")} == {f"edu_{p}_{n}" for n in (1, 2, 3) for p in ("institution", "credential")}
    assert {f for f in form.fields if f.startswith("cred_")} == {f"cred_{p}_{n}" for n in (1, 2, 3, 4)
                                                                 for p in ("name", "issuer", "identifier", "url")}
    assert form.fields["cred_name_4"].max_length == 200 and form.fields["cred_url_4"].max_length == 2048  # v2's own limits kept


# --- the phone number ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("typed", "country", "e164"), [
    ("+44 20 7946 0958", "GB", "+442079460958"),
    ("+44-20-7946-0958", "GB", "+442079460958"),
    ("0044 (20) 7946-0958", "GB", "+442079460958"),  # the 00 prefix
    ("+1 202.555.0143", "US", "+12025550143"),
    ("(202) 555-0143", "US", "+12025550143"),  # the national form, North American plan only
    ("1 202 555 0143", "US", "+12025550143"),
    ("+1 876 555 0143", "JM", "+18765550143"),  # a shared calling code
    ("+39 06 1234 5678", "IT", "+390612345678"),  # Italy keeps its trunk zero
    ("+7 912 345 67 89", "KZ", "+79123456789"),
])
def test_parity_form_phone_numbers_are_normalised_to_e164(typed, country, e164):
    assert countries.normalize_phone(typed, country) == e164


@pytest.mark.parametrize(("typed", "country", "reason"), [
    ("abc", "GB", "characters"), ("++44 20 7946 0958", "GB", "characters"), ("", "GB", "characters"),
    ("020 7946 0958", "GB", "international"),  # a national number outside the North American plan is not guessed
    ("+33 1 23 45 67 89", "GB", "country"),
    ("+44 20", "GB", "length"), ("+44 20 7946 0958 1234", "GB", "length"), ("202 555 014", "US", "length"),
    ("0202 555 0143", "US", "length"),
])
def test_parity_form_unreadable_phone_numbers_are_refused_with_a_reason(typed, country, reason):
    with pytest.raises(ValueError, match=f"^{reason}$"):
        countries.normalize_phone(typed, country)


@pytest.mark.django_db
def test_parity_form_a_national_north_american_number_is_stored_international(client):
    assert post(client, phone_country="US", phone="(202) 555-0143").status_code == 302
    fields = SubmissionVersion.objects.get().submitted_fields
    assert (fields["phone_e164"], fields["phone_country"]) == ("+12025550143", "US")


def test_parity_form_the_country_table_is_the_iso_3166_set_with_calling_codes():
    codes = [code for code, _, _ in countries.COUNTRIES]
    assert len(codes) == len(set(codes)) == 249
    assert all(len(c) == 2 and c.isascii() and c.isupper() for c in codes)
    assert all(cc.isdigit() and 1 <= len(cc) <= 3 and cc[0] != "0" for cc in countries.CALLING_CODES.values())
    assert (countries.CALLING_CODES["GB"], countries.CALLING_CODES["US"], countries.CALLING_CODES["KZ"]) == ("44", "1", "7")
    names = [name for _, name in countries.choices()]
    assert names == sorted(names, key=str.casefold) and countries.name("GB") == "United Kingdom"
    assert dict(countries.phone_choices())["GB"] == "United Kingdom (+44)"


# --- the dossier -----------------------------------------------------------------------------------------------

def test_parity_form_the_dossier_shows_the_answers_of_each_version(privileged_reset):
    from django.test import Client

    assert post(Client(), marketing_opt_in="on", **ROWS).status_code == 302
    app = Application.objects.get()
    # A version recorded before the fields existed (the first-generation answers absent) says so instead of guessing.
    SubmissionVersion.objects.create(application=app, version_number=app.next_version_number, origin="form",
                                     submitted_fields={"name": "Ada Example", "email": app.email, "reason": "Older shape."})
    page = logged_in(make_user(privileged_reset, "parity-reader")).get(change_url(app))
    body = page.content.decode()
    assert page.status_code == 200
    for shown in ("United Kingdom (GB)", "+442079460958", "read for United Kingdom", "Certification support only",
                  "yes (wording marketing-updates.v1)", "Synthetic Institute: BSc Computing", "1 row(s), see the claims",
                  "yes (wording credential-verification.v1)", "none recorded (a version before the first-generation fields)"):
        assert shown in body, shown


# --- erasure ---------------------------------------------------------------------------------------------------

def test_parity_form_erasure_clears_the_answers_with_the_submission(privileged_reset, decided):
    from django.test import Client

    assert post(Client(), marketing_opt_in="on", **ROWS).status_code == 302
    app = Application.objects.get()
    markers = ("442079460958", "Synthetic Institute", "BSc Computing", "SP-0001", "Synthetic Practitioner")
    owner = privileged_reset.connect("owner", autocommit=True)
    assert owner_scan(owner, *markers), "the answers are stored before the erasure"
    # The subject closes out: the applicant withdraws and the queued verification send is cancelled (nothing in flight).
    PendingAction.objects.filter(subject_id=app.public_ref).update(status=PendingAction.Status.CANCELLED)
    Application.objects.filter(pk=app.pk).update(stage="withdrawn")
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.status == "erased"
    assert SubmissionVersion.objects.get(application=app).submitted_fields == {}
    assert owner_scan(owner, *markers) == {}
    erased = Application.objects.get(pk=app.pk)
    assert (erased.email, erased.display_name) == ("[erased]", "[erased]")
