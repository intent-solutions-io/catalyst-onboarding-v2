"""The public request form (005 S1.2; 018 section 2; parity track 034 row 3, bead catalyst-v2-bgl.3).

Three layers, all stored in the same versioned, adopted submission (`SubmissionVersion.submitted_fields`), so a
version carries every answer the applicant gave at the time and the erasure path tombstones them as one object
(erasure.catalog, class `submissions`):

- the S1 fields `name`, `email`, `reason` (POL-03 placeholder set; limits match the model columns);
- the P3 claim fields under `claims` (P3-D-1): work samples, contribution, experience, confidential work and the
  credential rows; stored only when at least one is given (an S1-shaped submission otherwise);
- the first-generation answers (034 section 1.2 step 1, row 3): country of residence (ISO 3166-1 alpha-2), phone
  (E.164, with the country it was read for), the interest track (a short code), the optional marketing consent with
  the version of the wording it answered, the 18+ attestation, up to three education rows or the "none" tick, the
  credential rows made required-or-"none" (up to four; a row needs a name and an identifier or a link), and the
  verification consent with its wording version. `answers()` returns them for the service.

The limits of the new fields are the first-generation ones (text 150, up to 3 education and 4 certification rows);
the credential rows keep v2's own limits (CLAIM_MAX, URL_MAX). The consent labels are field labels, not approved
notice text (POL-17): the wording version strings are recorded so that a later wording change never re-labels an
earlier answer.
"""

from django import forms

from . import countries
from .identity import email_key

# S1 synthetic placeholder field set (POL-03): name, email, reason. Limits match the model columns.
NAME_MAX = 200
EMAIL_MAX = 320
REASON_MAX = 2000
# P3 claim fields (018 section 2, P3-D-1; synthetic wording until POL-17). All optional; stored in the same
# versioned, adopted submission under "claims", and only when at least one is given.
URL_MAX, NOTE_MAX, TEXT_MAX, CLAIM_MAX = 2048, 200, 2000, 200
SLOTS = (1, 2, 3)
# 034 row 3 (first-generation form v4): certification rows are up to four, education rows up to three, each text 150.
CERTIFICATION_SLOTS = (1, 2, 3, 4)
EDUCATION_SLOTS = (1, 2, 3)
ANSWER_TEXT_MAX = 150
PHONE_TYPED_MAX = (
    40  # room for spaces, punctuation and a prefix around at most 15 digits
)
MARKETING_WORDING_VERSION = "marketing-updates.v1"
VERIFICATION_WORDING_VERSION = "credential-verification.v1"


class InterestTrack(forms.ChoiceField):
    """The three first-generation answers by meaning (034 row 3), stored as the short code."""

    CERT_ONLY, CERT_AND_WORK, UNDECIDED = "cert_only", "cert_and_work", "undecided"
    CHOICES = (
        (CERT_ONLY, "Certification support only"),
        (CERT_AND_WORK, "Certification support, and consider me for project work"),
        (UNDECIDED, "Not sure yet"),
    )

    def __init__(self, **kwargs):
        # A select, not radio buttons: the phone-width browser check requires every control to be reached by the Tab
        # key, and a radio group is entered once and then walked with the arrow keys.
        super().__init__(choices=self.CHOICES, **kwargs)


INTEREST_LABELS = dict(InterestTrack.CHOICES)
PHONE_ERRORS = {
    "characters": "Enter a phone number using digits, spaces, parentheses, dots or hyphens.",
    "international": "Enter the number with its country code, starting with +.",
    "country": "The number's country code does not match the country you chose for it.",
    "length": "Enter a complete phone number: 8 to 15 digits including the country code.",
}


def _https_url(value):
    if value and not value.lower().startswith("https://"):
        raise forms.ValidationError(
            "Enter a link that starts with https://.", code="invalid"
        )
    return value


class AccessRequestForm(forms.Form):
    name = forms.CharField(max_length=NAME_MAX)
    email = forms.EmailField(max_length=EMAIL_MAX)
    residence_country = forms.ChoiceField(
        choices=countries.choices, label="Country of residence"
    )
    phone_country = forms.ChoiceField(
        choices=countries.phone_choices, label="Country for your phone number"
    )
    phone = forms.CharField(
        max_length=PHONE_TYPED_MAX,
        label="Phone number",
        help_text="With its country code, starting with +, or the national number for a North American country.",
    )
    reason = forms.CharField(max_length=REASON_MAX, widget=forms.Textarea)
    contribution = forms.CharField(
        max_length=TEXT_MAX,
        required=False,
        widget=forms.Textarea,
        label="What you personally did in the work you list",
    )
    experience = forms.CharField(
        max_length=TEXT_MAX,
        required=False,
        widget=forms.Textarea,
        label="Relevant experience",
    )
    confidential = forms.BooleanField(
        required=False,
        label="My relevant work is private or covered by confidentiality obligations",
    )
    confidential_description = forms.CharField(
        max_length=TEXT_MAX,
        required=False,
        widget=forms.Textarea,
        label="Describe the kind of work only: no client names, secrets or confidential material",
    )
    interest_track = InterestTrack(label="Your interest")
    no_degree = forms.BooleanField(
        required=False, label="I have no post-secondary education to list"
    )
    no_certifications = forms.BooleanField(
        required=False, label="I have no certifications to list"
    )
    verification_consent = forms.BooleanField(
        label="Intent Solutions may verify the education and certifications I list",
        error_messages={
            "required": "Verification consent is needed to send a request."
        },
    )
    marketing_opt_in = forms.BooleanField(
        required=False,
        label="Occasional updates from Intent Solutions by email (optional)",
    )
    age_attested = forms.BooleanField(
        label="I am 18 or older",
        error_messages={"required": "You must be 18 or older to request access."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for n in SLOTS:
            self.fields[f"work_url_{n}"] = forms.CharField(
                max_length=URL_MAX,
                required=False,
                validators=[_https_url],
                label=f"Work sample {n}: link",
            )
            self.fields[f"work_note_{n}"] = forms.CharField(
                max_length=NOTE_MAX,
                required=False,
                label=f"Work sample {n}: one-line description",
            )
        for n in EDUCATION_SLOTS:
            self.fields[f"edu_institution_{n}"] = forms.CharField(
                max_length=ANSWER_TEXT_MAX,
                required=False,
                label=f"Education {n}: institution",
            )
            self.fields[f"edu_credential_{n}"] = forms.CharField(
                max_length=ANSWER_TEXT_MAX,
                required=False,
                label=f"Education {n}: degree or qualification",
            )
        for n in CERTIFICATION_SLOTS:
            self.fields[f"cred_name_{n}"] = forms.CharField(
                max_length=CLAIM_MAX, required=False, label=f"Credential {n}: name"
            )
            self.fields[f"cred_issuer_{n}"] = forms.CharField(
                max_length=CLAIM_MAX, required=False, label=f"Credential {n}: issuer"
            )
            self.fields[f"cred_identifier_{n}"] = forms.CharField(
                max_length=CLAIM_MAX,
                required=False,
                label=f"Credential {n}: identifier",
            )
            self.fields[f"cred_url_{n}"] = forms.CharField(
                max_length=URL_MAX,
                required=False,
                validators=[_https_url],
                label=f"Credential {n}: issuer's verification link",
            )
        self.order_fields(
            [
                "name",
                "email",
                "residence_country",
                "phone_country",
                "phone",
                "reason",
                *(f"work_{part}_{n}" for n in SLOTS for part in ("url", "note")),
                "contribution",
                "experience",
                "confidential",
                "confidential_description",
                "interest_track",
                *(
                    f"edu_{part}_{n}"
                    for n in EDUCATION_SLOTS
                    for part in ("institution", "credential")
                ),
                "no_degree",
                *(
                    f"cred_{part}_{n}"
                    for n in CERTIFICATION_SLOTS
                    for part in ("name", "issuer", "identifier", "url")
                ),
                "no_certifications",
                "verification_consent",
                "marketing_opt_in",
                "age_attested",
            ]
        )

    # --- the stored shapes ---------------------------------------------------------------------------------------

    def claims(self) -> dict | None:
        """The claim fields as stored in the submission, or None when none was given (an S1-shaped submission)."""
        d = self.cleaned_data
        work = [
            {"url": d[f"work_url_{n}"], "note": d[f"work_note_{n}"]}
            for n in SLOTS
            if d[f"work_url_{n}"] or d[f"work_note_{n}"]
        ]
        credentials = [
            {
                "name": d[f"cred_name_{n}"],
                "issuer": d[f"cred_issuer_{n}"],
                "identifier": d[f"cred_identifier_{n}"],
                "url": d[f"cred_url_{n}"],
            }
            for n in CERTIFICATION_SLOTS
            if self._credential_given(n)
        ]
        claims = {
            "work": work,
            "contribution": d["contribution"],
            "experience": d["experience"],
            "credentials": credentials,
            "confidential": d["confidential"],
            "confidential_description": d["confidential_description"],
        }
        given = (
            work
            or credentials
            or d["contribution"]
            or d["experience"]
            or d["confidential"]
            or d["confidential_description"]
        )
        return claims if given else None

    def answers(self) -> dict:
        """The first-generation answers (034 row 3) as stored at the top level of the submission."""
        d = self.cleaned_data
        return {
            "residence_country": d["residence_country"],
            "phone_e164": d["phone_e164"],
            "phone_country": d["phone_country"],
            "interest_track": d["interest_track"],
            "marketing_opt_in": d["marketing_opt_in"],
            "marketing_wording_version": MARKETING_WORDING_VERSION,
            "age_attested": True,
            "education": [
                {
                    "institution": d[f"edu_institution_{n}"],
                    "credential": d[f"edu_credential_{n}"],
                }
                for n in EDUCATION_SLOTS
                if self._education_given(n)
            ],
            "no_degree": d["no_degree"],
            "no_certifications": d["no_certifications"],
            "verification_consent": True,
            "verification_wording_version": VERIFICATION_WORDING_VERSION,
        }

    # --- validation ----------------------------------------------------------------------------------------------

    def clean_email(self):
        email = self.cleaned_data["email"]
        try:
            key = email_key(email)
        except ValueError:
            raise forms.ValidationError("Enter a valid email address.", code="invalid")
        if (
            len(key) > EMAIL_MAX
        ):  # normalization (NFKC, IDNA) can lengthen an address past the column
            raise forms.ValidationError("Enter a valid email address.", code="invalid")
        return email

    def _education_given(self, n) -> bool:
        d = self.cleaned_data
        return bool(d.get(f"edu_institution_{n}") or d.get(f"edu_credential_{n}"))

    def _credential_given(self, n) -> bool:
        d = self.cleaned_data
        return any(
            d.get(f"cred_{part}_{n}")
            for part in ("name", "issuer", "identifier", "url")
        )

    def clean(self):
        d = super().clean()
        if d.get("phone") and d.get("phone_country"):
            try:
                d["phone_e164"] = countries.normalize_phone(
                    d["phone"], d["phone_country"]
                )
            except ValueError as why:
                self.add_error(
                    "phone",
                    forms.ValidationError(PHONE_ERRORS[str(why)], code="invalid"),
                )
        # Education: a started row needs both parts; at least one row or the tick, never both.
        education = 0
        for n in EDUCATION_SLOTS:
            if not self._education_given(n):
                continue
            education += 1
            for part in ("institution", "credential"):
                if not d.get(f"edu_{part}_{n}"):
                    self.add_error(
                        f"edu_{part}_{n}",
                        forms.ValidationError(
                            "Complete this entry or leave the row empty.",
                            code="required",
                        ),
                    )
        self._rows_or_tick(
            "no_degree",
            education,
            "List at least one education entry or tick this box.",
            "Either list your education or tick this box, not both.",
        )
        # Certifications: a started row needs a name and an identifier or a link; at least one row or the tick.
        certifications = 0
        for n in CERTIFICATION_SLOTS:
            if not self._credential_given(n):
                continue
            certifications += 1
            if not d.get(f"cred_name_{n}"):
                self.add_error(
                    f"cred_name_{n}",
                    forms.ValidationError(
                        "Name the credential or leave the row empty.", code="required"
                    ),
                )
            if not (d.get(f"cred_identifier_{n}") or d.get(f"cred_url_{n}")):
                self.add_error(
                    f"cred_identifier_{n}",
                    forms.ValidationError(
                        "Give the credential's identifier or its verification link.",
                        code="required",
                    ),
                )
        self._rows_or_tick(
            "no_certifications",
            certifications,
            "List at least one certification or tick this box.",
            "Either list your certifications or tick this box, not both.",
        )
        return d

    def _rows_or_tick(self, tick: str, rows: int, neither: str, both: str) -> None:
        ticked = self.cleaned_data.get(tick)
        if ticked and rows:
            self.add_error(tick, forms.ValidationError(both, code="invalid"))
        elif not ticked and not rows:
            self.add_error(tick, forms.ValidationError(neither, code="required"))
