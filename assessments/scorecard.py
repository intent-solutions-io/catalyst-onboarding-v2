"""The 019 section 9 scorecard (oc4.12; the weekly summary, f1u.7), counts only, read-only. Kept apart from the
decision service: it reads the advisory recommendation to count overrides, which is reporting, and TEST-P3-50 keeps
every output field out of the decision's control flow."""

from django.db.models import Count

from correspondence.models import Question, StaffItem

from .decisions import HUMAN_ONLY_CODES
from .models import AssessmentRun, QualificationDecision


SCORECARD_ROWS = (  # 019 section 9, every row, in its order (A candidate, B staff, C assessment, D delivery)
    "time_waiting", "clarification_burden", "abandoned_cases", "corrections_alternatives_complaints",
    "review_time", "exceptions_and_futile_reruns", "override_reasons", "reviewer_disagreement", "shell_or_database_edits",
    "unsupported_conclusions_missed_evidence", "citation_relevance", "instability", "insufficient_evidence_outcomes",
    "version_differences", "delivery")


def scorecard() -> dict:
    """The 019 section 9 scorecard, counts only, for the weekly summary (f1u.7). Every row of the table is emitted
    explicitly: a measurable row as {"value": ...}; a row this code cannot compute as {"value": None, "reason": ...}.
    Measurable today from existing records: the decision-time rows (by basis and outcome, every human-only code with
    an explicit zero, by policy reference, overrides against the advisory recommendation by reason code), the
    assessment staff items (open and resolved) with the runs that ended capped or failed, the days from adoption to
    decision, and the insufficient-evidence ratings per succeeded run. Everything that needs reviewer annotations,
    an incident log, delivery records or an owner-set definition is null with its reason. No name, reason text or
    identifier is in the output."""
    decisions = QualificationDecision.objects.all()
    human_only = decisions.filter(basis=QualificationDecision.Basis.HUMAN_ONLY)

    def by(queryset, *fields):
        return [dict(zip(fields, row[:-1]), count=row[-1]) for row in
                queryset.values_list(*fields).annotate(n=Count("id")).order_by(*fields)]

    def null(reason):
        return {"value": None, "reason": reason}

    waits = [(d.created_at - a.adopted_at).total_seconds() / 86400 for d in decisions.select_related("adopted_version")
             for a in [getattr(d.adopted_version, "adoption", None)] if a is not None]
    codes = {code: 0 for code in HUMAN_ONLY_CODES}
    codes.update({row["human_only_code"]: row["count"] for row in by(human_only, "human_only_code")})
    overrides = {}
    for d in decisions.filter(run__isnull=False).select_related("run"):
        advised = ((d.run.output or {}).get("recommendation") or "") if d.run.output else ""
        if advised and advised != d.outcome:
            overrides[d.reason_code] = overrides.get(d.reason_code, 0) + 1
    items = StaffItem.objects.filter(reason_code__startswith="assessment_")
    futile = AssessmentRun.objects.filter(status__in=("capped", "failed", "invalid_output", "abandoned"), trigger="staff_rerun").count()
    insufficient, succeeded = 0, 0
    for run in AssessmentRun.objects.filter(status="succeeded").only("output"):
        succeeded += 1
        insufficient += sum(1 for c in (run.output or {}).get("criteria") or [] if c.get("rating") == "insufficient_evidence")
    questions = Question.objects.exclude(round=0)
    per_application = [row["n"] for row in questions.values("application").annotate(n=Count("id"))]
    repeats = questions.values("application", "criterion_id").annotate(n=Count("id")).filter(n__gt=1).count()
    return {
        "decisions": decisions.count(),
        "by_basis_and_outcome": by(decisions, "basis", "outcome"),
        "human_only_by_code": [{"human_only_code": code, "count": codes[code]} for code in HUMAN_ONLY_CODES],
        "by_policy": by(decisions, "policy_ref"),
        "rows": {
            "time_waiting": {"value": {"decided_cases": len(waits), "max_days": round(max(waits), 2) if waits else 0,
                                       "mean_days": round(sum(waits) / len(waits), 2) if waits else 0}},
            "clarification_burden": {"value": {"applications_asked": len(per_application),
                                               "mean_questions": round(sum(per_application) / len(per_application), 2) if per_application else 0,
                                               "repeated_criterion": repeats}},
            "abandoned_cases": null("the owner has not set what counts as abandonment (019 section 9, minimum to interpret)"),
            "corrections_alternatives_complaints": null("no correction, alternative-route or complaint record exists in the database (POL-17 items, deferred to external applicants)"),
            "review_time": null("needs reviewer timing from awaiting_decision to decision; not derived from events in this version"),
            "exceptions_and_futile_reruns": {"value": {"assessment_items_open": items.filter(status="open").count(),
                                                       "assessment_items_resolved": items.filter(status="resolved").count(),
                                                       "runs_capped": AssessmentRun.objects.filter(status="capped").count(),
                                                       "runs_failed": AssessmentRun.objects.filter(status__in=("failed", "invalid_output", "abandoned")).count(),
                                                       "staff_reruns_ending_capped_or_failed": futile}},
            "override_reasons": {"value": [{"reason_code": code, "count": n} for code, n in sorted(overrides.items())]},
            "reviewer_disagreement": null("no second reviewer records a decision in this version (P3-D-9: the second actor is optional and has no screen)"),
            "shell_or_database_edits": null("its source is an incident log, which does not exist in the database; the count is kept by hand (030 Q8)"),
            "unsupported_conclusions_missed_evidence": null("needs reviewer annotations, which have no record in this version"),
            "citation_relevance": null("needs reviewer annotations, which have no record in this version"),
            "instability": null("needs two runs of one unchanged snapshot to compare; a succeeded snapshot never runs twice (018 section 14)"),
            "insufficient_evidence_outcomes": {"value": {"succeeded_runs": succeeded, "insufficient_evidence_ratings": insufficient}},
            "version_differences": {"value": by(decisions, "policy_ref", "prompt_pack", "rubric_version", "outcome")},
            "delivery": null("delivery records are not yet designed (after the pilot)"),
        },
    }
