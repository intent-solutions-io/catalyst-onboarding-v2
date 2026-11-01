"""The routine-advance policy (parity track bgl.12; 034 section 2.2 rows 15 to 18): a pure function over one typed
assessment result and the application's facts that names one of four outcomes. It is the only module that reads the
run's advisory fields (`recommendation`, `confidence`, the ratings, the proposed questions) to choose anything, and it
is consulted only by `routine.RoutineAdvance`, which runs only under `CATALYST_ROUTINE_ADVANCE_ACTIVATION` (0 in code).
Everywhere else the rule of 018 section 4 step 4 stands: no output field chooses a transition.

Outcomes:

- `advance_to_nda`: a routine applicant. The recommendation is admit at or above the confidence threshold, every
  required criterion is rated at or above `CATALYST_ROUTINE_ADVANCE_REQUIRED_RATING`, every other criterion at or above
  `CATALYST_ROUTINE_ADVANCE_OTHER_RATING`, and every rated finding rests on at least one evidence citation (an `E`
  alias): a rating resting on claims alone never advances anyone. The first generation advanced only when every
  required criterion was satisfied by evidence; the thresholds here are settings so the owner can tighten them.
- `ask_a_question`: the run proposed at least one question, a round is left and the round has room. The chosen
  proposals are returned; routine drafts, checks and sends them.
- `hold`: nothing is wrong with the case but automatic action is not possible now (automation paused, the contact
  not verified, an approved question still open, evidence pending). Routine retries a hold a bounded number of times.
- `needs_human`: the case stays on the decision screen exactly as today. A decline is never automatic (the first
  generation's rule too); so is anything flagged (injection, an inconsistent recommendation), an open identity item,
  the internal cohort's trial boundary (nothing is rated there, 033 Q6), an admit below the thresholds with nothing
  to ask, a hold recommendation, or exhausted rounds.

`rationale` turns the run's findings into the per-criterion record an automatic admit stores (capability and strength
of evidence, 019 section 5): no evidence means capability unknown, never a lack of ability.
"""

from dataclasses import dataclass

from .quotas import exceeds
from .schema import AssessmentOutput, ProposedQuestion

VERSION = "1"  # recorded with every verdict and every automatic decision; bump on any change to `decide`
ADVANCE, ASK, HOLD, NEEDS_HUMAN = "advance_to_nda", "ask_a_question", "hold", "needs_human"
OUTCOMES = (ADVANCE, ASK, HOLD, NEEDS_HUMAN)
CONFIDENCE = ("low", "medium", "high")
# Ratings in increasing order of support; `not_supported` is negative and meets no threshold.
RATING_RANK = {"not_supported": 0, "insufficient_evidence": 1, "partly_supported": 2, "supported": 3}
THRESHOLD_RATINGS = ("insufficient_evidence", "partly_supported", "supported")
# A run carrying any of these soft flags (schema.flags) is never acted on without a person.
BLOCKING_FLAGS = frozenset({"injection_suspected_by_model", "injection_markers_in_evidence", "citation_overlaps_an_injection_marker",
                            "inconsistent_recommendation", "not_supported_while_evidence_is_missing", "decline_without_a_negative_finding"})
# What an automatic admit records per criterion for each rating (capability, strength of evidence).
RECORD = {"supported": ("shown", "moderate"), "partly_supported": ("partly_shown", "weak"),
          "not_supported": ("not_shown", "weak"), "insufficient_evidence": ("unknown", "none")}


@dataclass(frozen=True)
class Thresholds:
    advance_confidence: str = "high"
    required_rating: str = "supported"
    other_rating: str = "partly_supported"

    @classmethod
    def from_settings(cls, settings) -> "Thresholds":
        return cls(settings.CATALYST_ROUTINE_ADVANCE_CONFIDENCE, settings.CATALYST_ROUTINE_ADVANCE_REQUIRED_RATING,
                   settings.CATALYST_ROUTINE_ADVANCE_OTHER_RATING)

    def problems(self) -> list[str]:
        found = []
        if self.advance_confidence not in CONFIDENCE:
            found.append("CATALYST_ROUTINE_ADVANCE_CONFIDENCE must be low, medium or high")
        for name, value in (("CATALYST_ROUTINE_ADVANCE_REQUIRED_RATING", self.required_rating),
                            ("CATALYST_ROUTINE_ADVANCE_OTHER_RATING", self.other_rating)):
            if value not in THRESHOLD_RATINGS:
                found.append(f"{name} must be insufficient_evidence, partly_supported or supported")
        return found


@dataclass(frozen=True)
class Facts:
    """What the policy knows about the application beside the run's output. All booleans default to the safe side."""
    required: frozenset = frozenset()  # the rubric's required criterion ids
    flags: tuple = ()  # the run's soft flags (schema.flags)
    round: int = 1  # the run's clarification round
    rounds: int | None = 3  # CATALYST_ASSESSMENT_ROUNDS
    room: int = 0  # questions this round may still send (CATALYST_QUESTIONS_PER_ROUND minus those approved)
    cohort_boundary: bool = True
    identity_item_open: bool = True
    paused: bool = True
    contact_verified: bool = False
    open_question: bool = True
    evidence_pending: bool = True


@dataclass(frozen=True)
class Verdict:
    outcome: str
    reason: str
    questions: tuple = ()  # the ProposedQuestion objects to ask, for `ask_a_question`

    def record(self) -> dict:
        return {"policy_version": VERSION, "outcome": self.outcome, "reason": self.reason, "questions": len(self.questions)}


def _at_least(rank: dict, value: str, threshold: str) -> bool:
    return rank[value] >= rank[threshold]


def meets_advance(output: AssessmentOutput, facts: Facts, thresholds: Thresholds) -> str:
    """"" when the output is a routine admit; otherwise the first reason it is not."""
    if output.recommendation != "admit":
        return "recommendation_not_admit"
    confidence = {c: i for i, c in enumerate(CONFIDENCE)}
    if not _at_least(confidence, output.confidence, thresholds.advance_confidence):
        return "confidence_below_threshold"
    for finding in output.criteria:
        threshold = thresholds.required_rating if finding.criterion_id in facts.required else thresholds.other_rating
        if finding.rating == "not_supported" or not _at_least(RATING_RANK, finding.rating, threshold):
            return "rating_below_threshold"
        if finding.rating != "insufficient_evidence" and not any(c.evidence_alias.startswith("E") for c in finding.citations):
            return "rating_rests_on_claims_only"
    return ""


def decide(output: AssessmentOutput, facts: Facts, thresholds: Thresholds | None = None) -> Verdict:
    thresholds = thresholds if thresholds is not None else Thresholds()
    if facts.cohort_boundary:
        return Verdict(NEEDS_HUMAN, "cohort_boundary")
    if facts.identity_item_open:
        return Verdict(NEEDS_HUMAN, "identity_item_open")
    if output.injection_suspected or BLOCKING_FLAGS & set(facts.flags):
        return Verdict(NEEDS_HUMAN, "flagged_for_a_person")
    if output.recommendation == "decline":
        return Verdict(NEEDS_HUMAN, "decline_is_never_automatic")
    blocked = ("evidence_pending" if facts.evidence_pending else "automation_paused" if facts.paused
               else "contact_not_verified" if not facts.contact_verified else "question_open" if facts.open_question else "")
    short = meets_advance(output, facts, thresholds)
    if not short:
        return Verdict(HOLD, blocked) if blocked else Verdict(ADVANCE, "routine_admit")
    if output.proposed_questions and not exceeds(facts.round + 1, facts.rounds) and facts.room > 0:
        if blocked:
            return Verdict(HOLD, blocked)
        return Verdict(ASK, "evidence_gap", tuple(output.proposed_questions[:facts.room]))
    if output.proposed_questions:
        return Verdict(NEEDS_HUMAN, "rounds_exhausted" if exceeds(facts.round + 1, facts.rounds) else "round_full")
    return Verdict(NEEDS_HUMAN, "hold_recommended" if output.recommendation == "hold" else short)


def rationale(output: AssessmentOutput, version: str = VERSION) -> dict:
    """The per-criterion record of an automatic admit, derived from the findings (decisions.record_routine_admit
    validates it like a human's). Each note names the policy and the rating; no model-written text enters it."""
    out = {}
    for finding in output.criteria:
        capability, strength = RECORD[finding.rating]
        cited = sum(c.evidence_alias.startswith("E") for c in finding.citations)
        out[finding.criterion_id] = {"capability": capability, "evidence_strength": strength if cited else ("none" if capability == "unknown" else "weak"),
                                     "note": f"Routine policy v{version}: the assessment rated this {finding.rating} on {cited} evidence citation(s)."}
    return out


def chosen(verdict: Verdict) -> tuple[ProposedQuestion, ...]:
    return verdict.questions
