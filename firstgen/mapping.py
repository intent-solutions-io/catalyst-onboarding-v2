"""Pure mappings from first-generation rows to v2 values (bgl.16; 035 sections 2 and 3). No database access here.

Stages (035 section 3): every first-generation state maps to the nearest v2 stage, the state itself is kept verbatim on
the import record, and anything v2 cannot express is a finding code. Three v2 stages are written only with a
qualification decision in the same transaction (assessments 0008): `declined` gets one, recording the owner's decline
on the first generation; `held` and `lapsed` map to stages that need none (`awaiting_decision`, and the stage the case
lapsed from), so no decision is invented.

Submissions (034 row 3; the form-fields branch, bgl.3): the first-generation answers are stored at the top level of
`submitted_fields` under the same keys v2's form writes (`residence_country`, `phone_e164`, `phone_country`,
`interest_track`, `marketing_opt_in`, `marketing_wording_version`, `age_attested`, `education`, `no_degree`,
`no_certifications`, `verification_consent`, `verification_wording_version`), the S1 fields as `name`, `email` and
`reason`, work links and certifications as `claims`, and what has no v2 key under `first_generation`. A value the first
generation did not record (an older form) stays null: nothing is defaulted into an answer the person never gave.
"""

import hashlib
import json
import re
from datetime import datetime

OPEN_STAGES = ("submitted", "contact_verified", "assessing", "awaiting_answers", "awaiting_decision", "agreements",
               "agreements_complete", "provisioning", "active")
LAPSE_RESUME = {"needs_information": "awaiting_answers", "nda_pending": "agreements", "setup_pending": "agreements"}
STAGES = {
    "reviewing": "assessing",
    "needs_information": "awaiting_answers",
    "held": "awaiting_decision",
    "nda_pending": "agreements",
    "setup_pending": "agreements",
    "release_pending": "agreements_complete",
    "provisioning": "provisioning",
    "active": "active",
    "suspended": "active",
    "offboarding": "closed",
    "offboarded": "closed",
    "withdrawn": "withdrawn",
    "declined": "declined",
}
# What a mapping loses or leaves to a person, by first-generation state (codes, reported per case).
STATE_FINDINGS = {
    "held": ["v1_held_maps_to_awaiting_decision"],
    "lapsed": ["v1_lapsed_maps_to_resume_stage"],
    "suspended": ["v1_suspended_has_no_v2_stage"],
    "offboarding": ["v1_offboarding_incomplete_revoke_by_hand"],
    "declined": ["v1_decline_recorded_as_human_only_decision"],
}
COMPLETED_AGREEMENT = ("completed", "archived", "durable")
OPEN_AGREEMENT = ("prepared", "sent", "partially_signed")
REASON_CODE = re.compile(r"^[a-z][a-z_]{2,39}$")


class Unmappable(ValueError):
    """A first-generation value with no rule: the case is refused, never guessed. The message is a code."""


def stage_for(state: str, resume_state: str, contact_verified: bool) -> str:
    if state == "requested":
        return "contact_verified" if contact_verified else "submitted"
    if state == "lapsed":
        return LAPSE_RESUME.get(resume_state, "awaiting_decision")
    if state not in STAGES:
        raise Unmappable(f"unknown_v1_state:{state}"[:64])
    return STAGES[state]


def iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def jsonable(row: dict, drop=()) -> dict:
    """A row as JSON-safe values, without the named columns."""
    return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in row.items() if k not in drop}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _education(row: dict) -> dict:
    credential = ", ".join(p for p in (row.get("degree_level"), row.get("field_of_study")) if p)
    return {"institution": row.get("institution") or "", "credential": credential}


def _certification(row: dict) -> dict:
    ref, kind = row.get("credential_ref") or "", row.get("ref_kind")
    return {"name": row.get("name") or "", "issuer": row.get("issuer") or "",
            "identifier": "" if kind == "url" else ref, "url": ref if kind == "url" else ""}


def submitted_fields(submission: dict, reference: str, credentials: list, kind: str) -> dict:
    """The v2 `submitted_fields` of one first-generation submission (an intake request or a revision), with the
    credential rows that belong to it (ordered by position)."""
    rows = sorted(credentials, key=lambda r: (r.get("kind") or "", r.get("position") or 0))
    education = [_education(r) for r in rows if r.get("kind") == "education"]
    certifications = [_certification(r) for r in rows if r.get("kind") == "certification"]
    work = [{"url": str(u), "note": ""} for u in (submission.get("work_links") or []) if u]
    fields = {
        "name": submission.get("full_name") or "",
        "email": submission.get("personal_email") or "",
        "reason": submission.get("building_text") or "",
        "residence_country": submission.get("residence_country"),
        "phone_e164": submission.get("phone_e164"),
        "phone_country": submission.get("phone_country"),
        "interest_track": submission.get("interest_track"),
        "marketing_opt_in": submission.get("marketing_opt_in"),
        "marketing_wording_version": submission.get("marketing_wording_version"),
        "age_attested": submission.get("age_attested"),
        "education": education,
        "no_degree": submission.get("no_degree_declared"),
        "no_certifications": submission.get("no_certifications_declared"),
        "verification_consent": (True if submission.get("verification_consent_at") else
                                 None if submission.get("verification_wording_version") is None else False),
        "verification_wording_version": submission.get("verification_wording_version"),
        "first_generation": {
            "kind": kind,
            "reference": reference,
            "form_version": submission.get("form_version"),
            "interest_wording_version": submission.get("interest_wording_version"),
            "provenance": submission.get("provenance", "native"),
            "submitted_at": iso(submission.get("created_at")),
            "marketing_opt_in_at": iso(submission.get("marketing_opt_in_at")),
            "verification_consent_at": iso(submission.get("verification_consent_at")),
        },
    }
    if work or certifications:
        fields["claims"] = {"work": work, "contribution": "", "experience": "", "credentials": certifications,
                            "confidential": False, "confidential_description": ""}
    return fields


def details_values(row: dict) -> dict:
    """What the applicant typed on a completed User Agreement (v1 `agreement_details`), under its own keys."""
    keys = ("legal_full_name", "residence", "mailing_address", "phone", "field_set", "address_line1", "address_line2",
            "locality", "region", "postal_code", "country_code")
    return {k: row.get(k) for k in keys}


def agreement_label(row: dict) -> str:
    """The version label a member-on-file record carries (a plain label, never an identifier: applications.members)."""
    return f"{row.get('document_version') or 'unknown'} (first generation)"


def reason_code(value, default: str) -> str:
    return value if isinstance(value, str) and REASON_CODE.match(value) else default
