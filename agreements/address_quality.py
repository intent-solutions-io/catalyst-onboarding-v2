"""Address-quality flags on the details read back from a signed agreement (bgl.8; 034 row 33).

The first generation flagged a short address, a missing country and a postal code that does not fit its country to the
owner, and never let a flag block a release. The same here: `flags` is a pure function of the structured values the
read-back produced (agreements.details); the staff screen shows the codes, a staff item carries them to the queue, and
nothing downstream reads them. No value is ever part of a flag: codes only.

The postal-code check covers a small set of countries whose format is unambiguous and whose members this cohort is
likely to include: the company is in the United States; Canada, the United Kingdom, Germany, France, the Netherlands
and Australia have one fixed national format each. Three countries that use no postal code, or an optional one, are
named so a blank is not a flag there. Everything else is `postal_code_unchecked`: reported, never counted as a problem.
"""

import re

MIN_ADDRESS_LENGTH = 20  # street, locality, region and postal code together, as the first generation counted it
POSTAL_PATTERNS = {
    "US": r"\d{5}(?:-\d{4})?",
    "CA": r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] ?\d[ABCEGHJ-NPRSTV-Z]\d",
    "GB": r"[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}",
    "DE": r"\d{5}",
    "FR": r"\d{5}",
    "NL": r"\d{4} ?[A-Z]{2}",
    "AU": r"\d{4}",
}
NO_POSTAL_CODE = {"AE", "HK", "IE"}  # Ireland's Eircode is optional
COUNTRY_NAMES = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "canada": "CA", "united kingdom": "GB", "great britain": "GB", "uk": "GB", "u.k.": "GB",
    "germany": "DE", "deutschland": "DE", "france": "FR", "netherlands": "NL", "the netherlands": "NL",
    "australia": "AU", "united arab emirates": "AE", "uae": "AE", "hong kong": "HK", "ireland": "IE",
}
NONE_WORDS = {"NONE", "N/A", "NA", "-", "NIL", "NO POSTAL CODE"}  # what a signer types where the country has none
ADVISORY = {"postal_code_unchecked"}  # reported, not a problem
ADDRESS_PARTS = ("address_line1", "address_line2", "locality", "region", "postal_code")


def country_code(value) -> str:
    """An ISO 3166-1 alpha-2 code for a dropdown value: a two-letter code as typed, or a name from the small table;
    else "" (the country is present but not one the check knows)."""
    text = " ".join(str(value or "").split())
    if re.fullmatch(r"[A-Za-z]{2}", text):
        return text.upper()
    return COUNTRY_NAMES.get(text.casefold(), "")


def normalise_postal(value) -> str:
    return " ".join(str(value or "").upper().split()).strip(" .,")


def flags(values: dict) -> tuple:
    """Reason codes for one set of structured details: `short`, `no_country`, `no_postal_code`, `postal_code_invalid`
    and the advisory `postal_code_unchecked`; empty when the address looks complete and checked."""
    found = []
    address = " ".join(" ".join(str(values.get(part) or "").split()) for part in ADDRESS_PARTS).split()
    if len(" ".join(address)) < MIN_ADDRESS_LENGTH:
        found.append("short")
    country = " ".join(str(values.get("country") or "").split())
    code = country_code(country)
    if not country:
        found.append("no_country")
    postal = normalise_postal(values.get("postal_code"))
    if code in POSTAL_PATTERNS:
        if not postal or postal in NONE_WORDS:
            found.append("no_postal_code")
        elif not re.fullmatch(POSTAL_PATTERNS[code], postal):
            found.append("postal_code_invalid")
    elif country and code not in NO_POSTAL_CODE:
        found.append("postal_code_unchecked")
    return tuple(found)


def problems(values: dict) -> tuple:
    """The flags that are problems: everything but the advisory codes."""
    return tuple(code for code in flags(values) if code not in ADVISORY)
