"""The assessment output contract (018 5.3, schema version 2) and its deterministic checks.

The pydantic model bounds the shape; `problems` then checks what a schema cannot: every criterion exactly once,
citations to aliases that were sent, quotes copied verbatim from exactly the text that was sent and long enough
to mean something (never a redaction placeholder), no rating resting on claims alone above partly_supported, no
negative rating resting on truncated evidence, and every model-written string free of links, markup, contact
details and control characters. Proposed questions are screened for credential, personal-data and
confidential-material requests. A valid output is not a true assessment: these checks prove shape and provenance
only (018 5.3); quality is a separate, human-scored evaluation (018 9 B).
"""

import re
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "2"
MIN_QUOTE_CHARS = 20  # letters or digits, after removing redaction placeholders
Rating = Literal["supported", "partly_supported", "not_supported", "insufficient_evidence"]
_UNSAFE_TEXT = re.compile(
    r"https?://|www\.|mailto:|javascript:|data:|\]\(|<[a-z/!?]|@|\b[a-z0-9-]+\.(com|org|net|io|dev|app|ai|co|ly|me|sh|fr|ca|in|us|eu|tv|cloud|tech|test)\b",
    re.I)
_NUMBER = re.compile(r"\+?\d[\d ()./-]{6,24}\d")
_REFUSED_QUESTION = re.compile(
    r"\b(pass(word|phrase|code)\w*|credential\w*|log-?in\w*|sign-?in\w*|api[ _-]?keys?|ssh[ _-]?keys?|private[ _-]?keys?"
    r"|tokens?|secrets?|seed[ _-]?phrases?|recovery[ _-]?(codes?|phrases?)|pins?|2fa|mfa|one-?time[ _-]?codes?|otp"
    r"|wallets?|bank\w*|account[ _-]?numbers?|card[ _-]?numbers?|salar\w*|income|ssn|social security"
    r"|passports?|driv\w*[ _-]?licen[cs]e|national[ _-]?id|id[ _-]?(cards?|documents?)|identity[ _-]?documents?"
    r"|date[ _-]?of[ _-]?birth|birth\w*|age|how old|nationalit\w*|citizenship|religio\w*|health|medical|disabilit\w*"
    r"|pregnan\w*|famil\w*|married|marital|children|home[ _-]?address|address|phone|ethnic\w*|race|sexual\w*"
    r"|source[ _-]?code|customer[ _-]?(lists?|data|names?)|client[ _-]?(data|secrets?|names?|lists?)|confidential\w*"
    r"|nda|contracts?|proprietary|pass[ _-]?words?|credit[ _-]?cards?|cvv|visas?|immigration\w*|gender\w*"
    r"|politic\w*|union\w*|criminal\w*|tax\w*)\b", re.I)
Text = Annotated[str, Field(max_length=200)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(Strict):
    evidence_alias: str = Field(pattern=r"^[CE][0-9]{1,2}$")
    quote: str = Field(min_length=1, max_length=300)


class Finding(Strict):
    criterion_id: str = Field(max_length=40)
    rating: Rating
    summary: str = Field(max_length=300)
    citations: list[Citation] = Field(default_factory=list, max_length=3)


class ProposedQuestion(Strict):
    text: str = Field(min_length=1, max_length=400)
    criterion_id: str = Field(max_length=40)
    why_needed: str = Field(max_length=200)


class AssessmentOutput(Strict):
    schema_version: Literal["2"]
    criteria: list[Finding] = Field(min_length=1, max_length=8)
    recommendation: Literal["admit", "decline", "hold"]
    recommendation_basis: str = Field(max_length=600)
    basis_criteria: list[str] = Field(min_length=1, max_length=8)
    confidence: Literal["low", "medium", "high"]
    proposed_questions: list[ProposedQuestion] = Field(default_factory=list, max_length=3)
    injection_suspected: bool = False
    injection_citations: list[Citation] = Field(default_factory=list, max_length=4)
    limitations: list[Text] = Field(default_factory=list, max_length=5)


def _unsafe(text: str) -> bool:
    phone = any(sum(ch.isdigit() for ch in m.group(0)) >= 9 for m in _NUMBER.finditer(text))  # not a year range
    return phone or bool(_UNSAFE_TEXT.search(text)) or any(
        unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs") for ch in text if ch not in "\n\t")


def _substance(quote: str) -> int:
    from .snapshot import PLACEHOLDERS

    for placeholder in PLACEHOLDERS:
        quote = quote.replace(placeholder, "")
    return sum(ch.isalnum() for ch in quote)


def problems(output: AssessmentOutput, request) -> list[str]:
    """Hard problems: any of these makes the output invalid (one repair, then staff)."""
    found = []
    ids = [c["id"] for c in request.criteria]
    seen = [f.criterion_id for f in output.criteria]
    if sorted(seen) != sorted(ids):
        found.append("criteria_do_not_match_the_rubric")
    if any(c not in ids for c in output.basis_criteria) or len(set(output.basis_criteria)) != len(output.basis_criteria):
        found.append("basis_criteria_invalid")
    texts = [output.recommendation_basis, *output.limitations]
    for finding in output.criteria:
        texts.append(finding.summary)
        if finding.rating != "insufficient_evidence" and not finding.citations:
            found.append("rating_without_citation")
        quotes = [(c.evidence_alias, c.quote) for c in finding.citations]
        if len(set(quotes)) != len(quotes):
            found.append("duplicate_citation")
        for citation in finding.citations:
            found.extend(_citation_problems(citation, request))
        if finding.citations and all(c.evidence_alias.startswith("C") for c in finding.citations) and \
                finding.rating in ("supported", "not_supported"):
            found.append("claims_only_rating_above_partly_supported")
        evidence = [request.items[c.evidence_alias] for c in finding.citations if c.evidence_alias in request.items
                    and c.evidence_alias.startswith("E")]
        if finding.rating == "not_supported" and evidence and all(item.truncated for item in evidence):
            found.append("not_supported_on_truncated_evidence")
    for citation in output.injection_citations:
        found.extend(_citation_problems(citation, request, minimum=False))
    if output.injection_suspected != bool(output.injection_citations):
        found.append("injection_flag_and_citations_disagree")
    for question in output.proposed_questions:
        texts.append(question.why_needed)
        if question.criterion_id not in ids:
            found.append("question_names_an_unknown_criterion")
        plain = question.text.translate(str.maketrans("\u2018\u2019\u201c\u201d\u2013\u2014", "''\"\"--"))
        from .snapshot import _EMAIL  # obfuscated addresses too ("a (at) b dot c"); stricter, for questions only

        if _unsafe(question.text) or _EMAIL.search(question.text) or _REFUSED_QUESTION.search(question.text) or \
                not plain.isascii():  # English only
            found.append("question_refused")
    if any(_unsafe(t) for t in texts):
        found.append("free_text_contains_a_link_contact_or_markup")
    return sorted(set(found))


def _citation_problems(citation, request, minimum: bool = True) -> list[str]:
    item = request.items.get(citation.evidence_alias)
    if item is None:
        return ["citation_to_an_alias_not_sent"]
    if citation.quote not in item.text:  # exactly the sanitized text that was sent
        return ["quote_not_found_verbatim"]
    floor = MIN_QUOTE_CHARS if minimum else 8  # an injection citation may be short, never junk
    if _substance(citation.quote) < min(floor, max(_substance(item.text), 1)):
        return ["quote_too_short_or_only_placeholders"]
    return []


def flags(output: AssessmentOutput, request) -> list[str]:
    """Soft flags: stored and shown to staff, never corrected and never blocking."""
    out = []
    required = {c["id"] for c in request.criteria if c.get("required")}
    by_id = {f.criterion_id: f for f in output.criteria}
    if output.recommendation == "admit" and any(
            by_id.get(c) is not None and by_id[c].rating in ("not_supported", "insufficient_evidence") for c in required):
        out.append("inconsistent_recommendation")
    if output.recommendation == "decline" and not any(f.rating == "not_supported" for f in output.criteria):
        out.append("decline_without_a_negative_finding")
    if getattr(request, "missing", None) and any(f.rating == "not_supported" for f in output.criteria):
        out.append("not_supported_while_evidence_is_missing")
    if any(f.citations and all(c.evidence_alias.startswith("C") for c in f.citations) and f.rating != "insufficient_evidence"
           for f in output.criteria):
        out.append("rating_rests_on_claims_only")
    if output.injection_suspected:
        out.append("injection_suspected_by_model")
    for finding in output.criteria:
        for citation in finding.citations:
            item = request.items.get(citation.evidence_alias)
            if item is None or citation.quote not in item.text:
                continue
            start = item.text.index(citation.quote)
            end = start + len(citation.quote)
            if any(s < end and start < e for s, e in item.marker_spans):
                out.append("citation_overlaps_an_injection_marker")
    if any(item.markers or item.marker_spans for item in request.items.values()):
        out.append("injection_markers_in_evidence")
    return sorted(set(out))
