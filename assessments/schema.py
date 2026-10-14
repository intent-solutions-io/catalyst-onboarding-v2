"""The assessment output contract (018 5.3, schema version 1) and its deterministic checks.

The pydantic model bounds the shape; `problems` then checks what a schema cannot: every criterion exactly once,
citations to aliases that were sent, quotes copied verbatim from exactly the text that was sent, no negative
rating resting on missing or truncated evidence. A valid output is not a true assessment: these checks prove shape
and provenance only (018 5.3); quality is a separate, human-scored evaluation (018 9 B).
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"
Rating = Literal["supported", "partly_supported", "not_supported", "insufficient_evidence"]
_URLISH = re.compile(r"https?://|www\.|<[a-z/!]", re.I)
_CREDENTIAL_ASK = re.compile(r"\b(password|passcode|api[ _-]?key|token|secret|private key|client (data|secret|name)s?)\b", re.I)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(Strict):
    evidence_alias: str = Field(pattern=r"^E[0-9]{1,2}$")
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
    schema_version: Literal["1"]
    criteria: list[Finding] = Field(min_length=1, max_length=8)
    recommendation: Literal["admit", "decline", "hold"]
    recommendation_basis: str = Field(max_length=600)
    basis_criteria: list[str] = Field(min_length=1, max_length=8)
    confidence: Literal["low", "medium", "high"]
    proposed_questions: list[ProposedQuestion] = Field(default_factory=list, max_length=3)
    injection_suspected: bool = False
    injection_citations: list[Citation] = Field(default_factory=list, max_length=4)
    limitations: list[str] = Field(default_factory=list, max_length=5)


def problems(output: AssessmentOutput, request) -> list[str]:
    """Hard problems: any of these makes the output invalid (one repair, then staff)."""
    found = []
    ids = [c["id"] for c in request.criteria]
    seen = [f.criterion_id for f in output.criteria]
    if sorted(seen) != sorted(ids):
        found.append("criteria_do_not_match_the_rubric")
    if any(c not in ids for c in output.basis_criteria):
        found.append("basis_names_an_unknown_criterion")
    for finding in output.criteria:
        if finding.rating != "insufficient_evidence" and not finding.citations:
            found.append("rating_without_citation")
        if _URLISH.search(finding.summary):
            found.append("summary_contains_a_link_or_markup")
        for citation in finding.citations:
            found.extend(_citation_problems(citation, request))
        if finding.rating == "not_supported" and finding.citations and all(
                request.items[c.evidence_alias].truncated for c in finding.citations if c.evidence_alias in request.items):
            found.append("not_supported_on_truncated_evidence")
    for citation in output.injection_citations:
        found.extend(_citation_problems(citation, request))
    if output.injection_suspected and not output.injection_citations:
        found.append("injection_flag_without_citation")
    for question in output.proposed_questions:
        if question.criterion_id not in ids:
            found.append("question_names_an_unknown_criterion")
        if _URLISH.search(question.text) or "@" in question.text or _CREDENTIAL_ASK.search(question.text):
            found.append("question_refused")
    return sorted(set(found))


def _citation_problems(citation, request) -> list[str]:
    item = request.items.get(citation.evidence_alias)
    if item is None:
        return ["citation_to_an_alias_not_sent"]
    if citation.quote not in item.text:  # exactly the sanitized text that was sent
        return ["quote_not_found_verbatim"]
    return []


def flags(output: AssessmentOutput, request) -> list[str]:
    """Soft flags: stored and shown to staff, never corrected and never blocking."""
    out = []
    required = {c["id"] for c in request.criteria if c.get("required")}
    if output.recommendation == "admit" and any(
            f.criterion_id in required and f.rating == "not_supported" for f in output.criteria):
        out.append("inconsistent_recommendation")
    if output.injection_suspected:
        out.append("injection_suspected_by_model")
    for finding in output.criteria:
        for citation in finding.citations:
            item = request.items.get(citation.evidence_alias)
            if item is not None and item.markers and any(m in citation.quote for m in item.marker_spans):
                out.append("citation_overlaps_an_injection_marker")
    if any(item.markers for item in request.items.values()):
        out.append("injection_markers_in_evidence")
    return sorted(set(out))
