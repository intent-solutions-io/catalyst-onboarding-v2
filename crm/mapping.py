"""The field map from a v2 application to a Twenty person, and the applicant file note (bgl.14; 034 rows 42 and 43).

Pure code: no database, no HTTP. `crm.projection` gathers `Facts` from the v2 records and uses this module to decide
what Twenty should show. The fields, their names and their option values are the first generation's (its projection
`cpn-projection.v2`), so the CRM looks the same after the swap; what differs is recorded here and in the bead:

- `cpnCaseState` keeps the first generation's option values (a Twenty SELECT refuses any other), so each v2 stage is
  mapped to the nearest first-generation state (`STAGE_STATE`, the inverse of the import's `firstgen.mapping.STAGES`);
- the confirmed User Agreement details (legal name, phone, mailing address) are filled only where Twenty is blank,
  here and in the daily fill, never overwritten (the first generation's projection overwrote them for its own cases;
  its daily fill, which v2's replaces, already filled only blanks);
- `cpnAgreementRefs` carries type, version and status, never a provider envelope id;
- the phone is written whole (E.164) into the number with no calling-code split, and the address country as the code
  given: v2 carries no calling-code or country-name table.

Never projected: a signing or setup link, a token, a password, a document, an envelope id. Unknown stays blank: a value
the records do not hold is not sent (absent = not projected), and marketing consent is true only from an explicit
source.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

PROJECTION_VERSION = "cpn-projection.v3"  # v3: the v2 stage map and blank-only details (module docstring)
FILE_VERSION = "applicant-file.v3"
TITLE_PREFIX = "Applicant file — "
INTEREST_TRACKS = ("cert_only", "cert_and_work", "undecided")
LEAD_SOURCES = ("CATALYST_REQUEST_ACCESS", "LEGACY_IMPORT")
LINKEDIN_HOSTS = ("linkedin.com",)
# User Agreement versions whose text carries the communications clause: empty until counsel approves one, as in the
# first generation, so a signed agreement is never read as marketing consent today.
CONSENT_UA_VERSIONS: frozenset = frozenset()

# v2 stage -> the first generation's case state (its SELECT option values). `agreements` is refined by the NDA's state.
STAGE_STATE = {
    "submitted": "REQUESTED", "contact_verified": "REQUESTED", "evidence": "REVIEWING", "assessing": "REVIEWING",
    "awaiting_answers": "NEEDS_INFORMATION", "awaiting_decision": "REVIEWING", "on_hold": "HELD",
    "admitted": "NDA_PENDING", "agreements": "NDA_PENDING", "agreements_complete": "RELEASE_PENDING",
    "provisioning": "PROVISIONING", "active": "ACTIVE", "declined": "DECLINED", "withdrawn": "WITHDRAWN",
    "closed": "OFFBOARDED",
}
STATE_NEXT_ACTION = {
    "REQUESTED": "REVIEW_APPLICATION", "REVIEWING": "REVIEW_APPLICATION", "NEEDS_INFORMATION": "AWAIT_APPLICANT_INFO",
    "NDA_PENDING": "AWAIT_NDA_SIGNATURE", "SETUP_PENDING": "AWAIT_SETUP_AND_SIGNING", "RELEASE_PENDING": "DECIDE_RELEASE",
    "PROVISIONING": "PROVISION_ACCESS", "HELD": "RESOLVE_HOLD", "ACTIVE": "NONE", "DECLINED": "NONE",
    "WITHDRAWN": "NONE", "OFFBOARDED": "NONE",
}
NEXT_ACTION_TEXT = {
    "REVIEW_APPLICATION": "Staff: review the application and record a decision.",
    "AWAIT_APPLICANT_INFO": "Applicant: answer the open questions.",
    "AWAIT_NDA_SIGNATURE": "Applicant: sign the NDA.",
    "AWAIT_SETUP_AND_SIGNING": "Applicant: sign the User Agreement.",
    "DECIDE_RELEASE": "Staff: approve the company mailbox.",
    "PROVISION_ACCESS": "Service: create the company mailbox and send the set-up invitation.",
    "RESOLVE_HOLD": "Staff: resolve the hold.",
    "RESOLVE_EXCEPTION": "Staff: an item is open on this application; see the staff queue.",
    "NONE": "None.",
}
if set(STAGE_STATE.values()) | {"SETUP_PENDING"} != set(STATE_NEXT_ACTION):
    raise RuntimeError("the stage map and the next-action map disagree")  # import-time check

# Owned fields: the v2 records are authoritative; a person's edit is noticed (a staff item), then overwritten.
OWNED = ("cpnCaseId", "cpnCaseRef", "cpnCaseState", "cpnInterestTrack", "cpnNextAction", "cpnException",
         "cpnAgreementRefs", "cpnWorkLinks", "cpnLeadSource", "cpnRequestedAt", "cpnMarketingOptIn",
         "cpnMarketingOptInAt", "cpnMarketingOptInSource")
# Never written: the first generation's legacy free-text fields.
LEGACY_FIELDS = frozenset({"cpnStatus", "cpnNextStep", "cpnSource", "cpnLastContacted", "cohort"})
COMPOSITES = {
    "name": ("firstName", "lastName"),
    "phones": ("primaryPhoneNumber", "primaryPhoneCallingCode", "primaryPhoneCountryCode"),
    "mailingAddress": ("addressStreet1", "addressStreet2", "addressCity", "addressState", "addressPostcode",
                       "addressCountry"),
}
DETAIL_FIELDS = tuple(COMPOSITES)  # the User Agreement details: filled only where Twenty is blank
BOOLEANS = ("cpnException", "cpnMarketingOptIn")
TRI_STATE = ("cpnMarketingOptIn",)
DATES = ("cpnRequestedAt", "cpnMarketingOptInAt", "cpnProjectedAt")
if LEGACY_FIELDS & set(OWNED + DETAIL_FIELDS):
    raise RuntimeError("the projection must never write a legacy field")  # import-time check


@dataclass(frozen=True)
class Consent:
    opt_in: bool | None = None  # None: unknown, never projected
    at: datetime | None = None
    source: str = ""


@dataclass(frozen=True)
class Facts:
    """Everything the field map needs about one application, already read from the v2 records."""

    case_id: str
    state: str
    reference: str = ""
    interest_track: str = ""
    exception: bool = False
    agreements: tuple = ()  # (type key, version, status)
    work_links: tuple = ()
    lead_source: str = ""
    requested_at: datetime | None = None
    consent: Consent = Consent()
    contact_email: str = ""
    intake_name: str = ""
    intake_phone: str = ""
    details: dict = field(default_factory=dict)  # Twenty composite values from confirmed User Agreement details


def iso(moment: datetime) -> str:
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _iso_seconds(value) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def next_action(state: str, exception: bool) -> str:
    return "RESOLVE_EXCEPTION" if exception else STATE_NEXT_ACTION.get(state, "NONE")


def split_name(full_name: str) -> tuple[str, str]:
    """(first, family): the last word is the family name; a single word stays first (the first generation's rule)."""
    words = str(full_name or "").split()
    if len(words) < 2:
        return " ".join(words), ""
    return " ".join(words[:-1]), words[-1]


def is_linkedin(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith(f".{h}") for h in LINKEDIN_HOSTS)


def split_links(links) -> tuple[str, tuple]:
    linkedin = next((u for u in links if is_linkedin(u)), "")
    return linkedin, tuple(u for u in links if u != linkedin)


def linkedin_value(url: str) -> dict:
    return {"primaryLinkUrl": url, "primaryLinkLabel": "", "secondaryLinks": []}


def phone_value(e164: str, country: str = "") -> dict:
    return {"primaryPhoneNumber": str(e164 or "").strip(), "primaryPhoneCallingCode": "",
            "primaryPhoneCountryCode": str(country or "").strip().upper()}


def desired_owned(f: Facts) -> dict:
    """The owned fields the records can speak for right now (an absent source is not projected)."""
    values = {"cpnCaseId": f.case_id, "cpnCaseState": f.state, "cpnNextAction": next_action(f.state, f.exception),
              "cpnException": bool(f.exception)}
    if f.reference:
        values["cpnCaseRef"] = f.reference
    if f.interest_track in INTEREST_TRACKS:
        values["cpnInterestTrack"] = f.interest_track.upper()
    if f.agreements:
        values["cpnAgreementRefs"] = "; ".join(f"{t}:{v}:{s}" for t, v, s in f.agreements)
    _linkedin, others = split_links(f.work_links)
    if others:
        values["cpnWorkLinks"] = "\n".join(others)
    if f.lead_source in LEAD_SOURCES:
        values["cpnLeadSource"] = f.lead_source
    if f.requested_at is not None:
        values["cpnRequestedAt"] = iso(f.requested_at)
    if f.consent.opt_in is not None:
        values["cpnMarketingOptIn"] = f.consent.opt_in
        if f.consent.source:
            values["cpnMarketingOptInSource"] = f.consent.source
        if f.consent.opt_in and f.consent.at is not None:
            values["cpnMarketingOptInAt"] = iso(f.consent.at)
    return values


def create_only(f: Facts) -> dict:
    """Set when Catalyst creates the person, never owned afterwards: the matching email, the LinkedIn link and, until
    confirmed details exist, the intake name (split) and phone."""
    values = {}
    if f.contact_email:
        values["emails"] = {"primaryEmail": f.contact_email.strip(), "additionalEmails": []}
    linkedin, _others = split_links(f.work_links)
    if linkedin:
        values["linkedinLink"] = linkedin_value(linkedin)
    if f.intake_name:
        first, family = split_name(f.intake_name)
        values["name"] = {"firstName": first, "lastName": family}
    if f.intake_phone:
        values["phones"] = {**phone_value(f.intake_phone), "additionalPhones": []}
    values.update({k: dict(v) for k, v in f.details.items()})  # confirmed details win over the intake values
    if "phones" in values:
        values["phones"].setdefault("additionalPhones", [])
    return values


def fill_unowned(f: Facts, person: dict) -> dict:
    """Unowned values for an existing person, only where Twenty is still blank or still shows exactly what an earlier
    write put there: the LinkedIn link while none is set, and a whole intake name split into first and family name."""
    values = {}
    linkedin, _others = split_links(f.work_links)
    current = str(((person.get("linkedinLink") or {}).get("primaryLinkUrl")) or "").strip()
    if linkedin and not current:
        values["linkedinLink"] = linkedin_value(linkedin)
    if f.intake_name and "name" not in f.details:
        first, family = split_name(f.intake_name)
        if family and normalize("name", person.get("name")) == {"firstName": f.intake_name.strip(), "lastName": ""}:
            values["name"] = {"firstName": first, "lastName": family}
    return values


def details_values(values: dict) -> dict:
    """Twenty composite values from one confirmed User Agreement details version (`AgreementDetailsVersion.values`),
    under the keys the first-generation import writes (firstgen.mapping.details_values). A key the version does not
    hold is not projected; a composite with nothing in it is left out."""
    v = {k: str(values.get(k) or "").strip() for k in (
        "legal_full_name", "legal_given_names", "legal_family_names", "phone", "phone_e164", "mailing_address",
        "address_line1", "address_line2", "locality", "region", "postal_code", "country_code")}
    out = {}
    if v["legal_given_names"]:
        out["name"] = {"firstName": v["legal_given_names"], "lastName": v["legal_family_names"]}
    elif v["legal_full_name"]:
        first, family = split_name(v["legal_full_name"])
        out["name"] = {"firstName": first, "lastName": family}
    phone = v["phone_e164"] or v["phone"]
    if phone:
        out["phones"] = phone_value(phone, v["country_code"])
    street = v["address_line1"] or v["mailing_address"]
    if street:
        out["mailingAddress"] = {"addressStreet1": " ".join(street.split()), "addressStreet2": v["address_line2"],
                                 "addressCity": v["locality"], "addressState": v["region"],
                                 "addressPostcode": v["postal_code"], "addressCountry": v["country_code"].upper()}
    return out


def normalize(name: str, value):
    """The comparable form of a Twenty value for a field this map writes (only the keys it writes)."""
    if name in COMPOSITES:
        source = value if isinstance(value, dict) else {}
        return {k: "" if source.get(k) is None else str(source.get(k)).strip() for k in COMPOSITES[name]}
    if name in BOOLEANS:
        return None if (name in TRI_STATE and value is None) else bool(value)
    if name in DATES:
        return _iso_seconds(value)
    return "" if value is None else str(value).strip()


def value_hash(name: str, value) -> str:
    """SHA-256 of the canonical value: stored instead of the value, so no copy of it is kept here."""
    encoded = json.dumps(normalize(name, value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{name}\n{encoded}".encode()).hexdigest()


def is_blank(name: str, value) -> bool:
    canonical = normalize(name, value)
    if isinstance(canonical, dict):
        return not any(canonical.values())
    return canonical in ("", False, None)


def _fold(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def blank_fill(desired: dict, person: dict) -> tuple[dict, list]:
    """(patch, conflicts) for the User Agreement details: a composite Twenty holds nothing of is written whole; one
    whose filled parts all equal the confirmed values gets its blank parts; one with a different value is a conflict,
    reported and never overwritten."""
    patch, conflicts = {}, []
    for name, want in desired.items():
        have = normalize(name, person.get(name))
        want = normalize(name, want)
        if all(_fold(have[k]) == _fold(want[k]) or not want[k] for k in want):
            continue  # Twenty already shows it (case and spacing aside)
        if any(have[k] and want[k] and _fold(have[k]) != _fold(want[k]) for k in want):
            conflicts.append(name)
            continue
        merged = {k: have[k] or want[k] for k in want}
        if name == "phones":
            merged["additionalPhones"] = (person.get("phones") or {}).get("additionalPhones") or []
        patch[name] = merged
    return patch, conflicts


def patch_value(name: str, desired, person: dict):
    if name == "phones":
        return {**desired, "additionalPhones": (person.get("phones") or {}).get("additionalPhones") or []}
    return desired


# --- the applicant file note ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NoteFacts:
    case_id: str
    full_name: str
    state: str
    next_action: str
    requested_at: datetime | None = None
    source: str = ""
    reference: str = ""
    track: str = ""
    own_words: str = ""
    links: tuple = ()
    decisions: tuple = ()  # (outcome, basis, at)
    agreements: tuple = ()  # (type key, version, issue status, signing status, created at)
    residence: str = ""
    access: tuple = ()  # (address, status, created at) or ()


TRACK_LABELS = {"cert_only": "Certification support only",
                "cert_and_work": "Certification support, and project work",
                "undecided": "Not sure yet"}
DOCUMENT_NAMES = {"nda": "Mutual NDA", "user_agreement": "User Agreement"}
MAX_OWN_WORDS = 4000
MAX_URL = 300
WITHHELD = "[link withheld]"


def _day(moment) -> str:
    return moment.strftime("%Y-%m-%d") if moment else "not yet"


def _line(text) -> str:
    """One line of plain text: whitespace collapsed and markdown structure defused, so text an applicant typed stays
    text in whoever's browser opens the note."""
    flat = " ".join(str(text or "").split())
    return flat.replace("|", "/").replace("<", "(").replace(">", ")").replace("[", "(").replace("]", ")")


def safe_url(url) -> str:
    """A public https web address as text, or the withheld marker: never a credential, a query or a fragment."""
    text = str(url or "").strip()
    if not text or len(text) > MAX_URL or any(c.isspace() or c in "<>\"'|()[]" for c in text):
        return WITHHELD
    try:
        parts = urlsplit(text)
    except ValueError:
        return WITHHELD
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        return WITHHELD
    return text


def title_for(full_name: str) -> str:
    """The note's title, also its lookup key in a Twenty filter: no double quote or backslash."""
    name = " ".join(str(full_name or "").replace('"', "'").replace("\\", " ").split())[:150]
    return f"{TITLE_PREFIX}{name or 'name not given'}"


def marker(case_id: str) -> str:
    """The line that marks a note as this application's file (so a note whose create reply was lost is adopted)."""
    return f"case {case_id}, {FILE_VERSION}"


def is_marked(note: dict, case_id: str) -> bool:
    return f"case {case_id}," in str(((note.get("bodyV2") or {}).get("markdown")) or "")


def render(f: NoteFacts) -> tuple[str, str]:
    """(title, markdown body). Deterministic: the same facts always give the same text."""
    source = {"CATALYST_REQUEST_ACCESS": "Request-access form", "LEGACY_IMPORT": "Imported from the earlier request form",
              "FIRST_GENERATION": "The first-generation onboarding service"}.get(f.source, "Not recorded")
    words = str(f.own_words or "").strip()[:MAX_OWN_WORDS]
    quoted = [f"> {_line(part)}" if part.strip() else ">" for part in words.splitlines()] or ["> (nothing recorded)"]
    lines = ["## Application", "", f"- **Requested:** {_day(f.requested_at)}", f"- **Source:** {source}",
             f"- **Reference:** {_line(f.reference) or 'none'}",
             f"- **Track:** {TRACK_LABELS.get(f.track, _line(f.track) or 'not recorded')}",
             "", "**What they said they are building (their words):**", "", *quoted,
             "", "**Links they submitted:**", "", *([f"- {safe_url(u)}" for u in f.links] or ["- none"]), ""]
    lines += ["## Decision", ""]
    lines += [f"- **{_line(o).capitalize()}** on {_day(at)} ({'human-only assessment' if b == 'human_only' else 'model-assisted assessment'})"
              for o, b, at in f.decisions] or ["No decision recorded yet."]
    lines += ["", "## Agreements", ""]
    for key, version, issue, signing, at in f.agreements:
        lines.append(f"- **{DOCUMENT_NAMES.get(key, _line(key))} (template {_line(version)}):** {_line(issue)}, "
                     f"signing {_line(signing)} (created {_day(at)})")
    if not f.agreements:
        lines.append("None sent yet.")
    lines += ["", "## Details confirmed for the User Agreement", ""]
    lines.append(f"- **Residence:** {_line(f.residence)}" if f.residence else "Not confirmed yet.")
    lines += ["", "## Access", ""]
    if f.access:
        address, status, at = f.access
        lines += [f"- **Company mailbox:** {_line(address)} ({_line(status)})", f"- **Reserved:** {_day(at)}"]
    else:
        lines.append("No company mailbox yet.")
    lines += ["", "## Next action", "",
              f"{NEXT_ACTION_TEXT.get(f.next_action, _line(f.next_action))} Case state: {_line(f.state)}.", "",
              "---", "",
              f"_Kept current automatically by Catalyst onboarding ({marker(f.case_id)}). Edits made here are replaced "
              "at the next update; write your own observations in a separate note._"]
    return title_for(f.full_name), "\n".join(lines)


def note_sha256(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
