"""Read-only selection reporting, kept outside the qualification decision path (f1u.7)."""

from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from . import scorecard
from .staff_views import staff_page


ROW_LABELS = (
    "Time waiting",
    "Clarification burden",
    "Abandoned cases",
    "Corrections, alternatives and complaints",
    "Review time",
    "Exceptions and unsuccessful reruns",
    "Override reasons",
    "Reviewer disagreement",
    "Shell or database edits",
    "Unsupported conclusions and missed evidence",
    "Citation relevance",
    "Instability",
    "Insufficient-evidence outcomes",
    "Version differences",
    "Delivery outcomes",
)

FIELD_LABELS = {
    "decided_cases": "Decided cases",
    "max_days": "Longest wait (days)",
    "mean_days": "Mean wait (days)",
    "applications_asked": "Applications asked questions",
    "mean_questions": "Mean questions per application asked",
    "repeated_criterion": "Application/criterion pairs asked more than once",
    "assessment_items_open": "Open assessment staff items",
    "assessment_items_resolved": "Resolved assessment staff items",
    "runs_capped": "Historical capped runs",
    "runs_failed": "Failed, invalid or abandoned runs",
    "staff_reruns_ending_capped_or_failed": "Staff reruns ending capped or unsuccessful",
    "succeeded_runs": "Successful runs",
    "insufficient_evidence_ratings": "Insufficient-evidence ratings",
    "reason_code": "Reason code",
    "count": "Count",
    "policy_ref": "Policy",
    "prompt_pack": "Prompt pack",
    "rubric_version": "Rubric version",
    "outcome": "Outcome",
}


def report_rows(card):
    """Use the CLI's exact measurements; unknown remains distinct from measured zero."""
    rows = []
    for key, label in zip(scorecard.SCORECARD_ROWS, ROW_LABELS, strict=True):
        row = card["rows"][key]
        value = row["value"]
        records = (
            value if isinstance(value, list) else [value] if value is not None else []
        )
        rows.append(
            {
                "label": label,
                "known": value is not None,
                "reason": row.get("reason", ""),
                "records": [
                    [
                        (FIELD_LABELS[field], str(count))
                        for field, count in record.items()
                    ]
                    for record in records
                ],
            }
        )
    return rows


@require_GET
@staff_page("record_qualification_decision")
def selection_report(request):
    card = scorecard.scorecard()
    rows = report_rows(card)
    return render(
        request,
        "assessments/staff/scorecard.html",
        {
            "card": card,
            "rows": rows,
            "generated_at": timezone.now(),
            "waiting": card["rows"]["time_waiting"]["value"],
            "questions": card["rows"]["clarification_burden"]["value"],
            "exceptions": card["rows"]["exceptions_and_futile_reruns"]["value"],
            "unknown_count": sum(not row["known"] for row in rows),
        },
    )
