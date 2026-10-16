"""The clarification loop (018 section 4 steps 5 and 8, section 15; 019 section 5; task 3B.3).

- `propose_from_run`: inside a successful run's record transaction, the run's proposed questions become
  `Question(origin=model, approval_state=proposed)` rows through `correspondence.questions.create_question`. Each
  names its criterion, the evidence gap and any alternative route; duplicates are dropped; at most
  `CATALYST_QUESTIONS_PER_ROUND` per round, and none after the last round. **No stage change and nothing sent:**
  only staff approval sends a question (P3-D-5), and approving the first one opens the round
  (`awaiting_decision → awaiting_answers`, a staff act in `correspondence.outbound.approve_question`).
- `answers_settled` (the `CATALYST_ANSWERS_CONFIRMED_HOOK`): after staff confirm an outcome or withdraw a
  question. When no approved question is still open or awaiting processing, the application is reassessed on a
  new snapshot that includes the confirmed answers (round n+1). A duplicate trigger is a no-op (the stage is no
  longer `awaiting_answers`); the same snapshot never runs twice (TEST-P3-07). After the last round, the case
  returns to staff for a decision instead.

Nothing here reads the run's advisory outcome fields; only its proposed questions (TEST-P3-50).
"""

from django.conf import settings

from applications.models import Stage
from applications.stages import transition
from correspondence.common import Refused
from correspondence.models import Question
from correspondence.questions import create_question

from .models import AssessmentRun

OPEN = (Question.Status.OPEN, Question.Status.REPLY_PENDING)


def propose_from_run(run, output) -> int:
    if run.round >= settings.CATALYST_ASSESSMENT_ROUNDS:
        return 0  # a question asked in the last round could never be reassessed
    already = Question.objects.filter(application_id=run.application_id, origin=Question.Origin.MODEL, round=run.round).count()
    created = 0
    for proposal in output.proposed_questions:
        if already + created >= settings.CATALYST_QUESTIONS_PER_ROUND:
            break
        try:
            question = create_question(
                run.application, text=proposal.text, origin=Question.Origin.MODEL, criterion_id=proposal.criterion_id,
                evidence_gap=proposal.why_needed, alternative_route=proposal.alternative_route,
                requires_evidence=proposal.requires_evidence, raised_by=f"run:{run.public_id}", round=run.round,
                actor=f"assessment_run:{run.public_id}")
        except Refused:
            continue  # the output checks already refuse these; a second screen never sends anything
        created += question is not None
    return created


def current_round(application) -> int:
    latest = AssessmentRun.objects.filter(application=application, status=AssessmentRun.Status.SUCCEEDED).order_by("-round").first()
    return latest.round if latest is not None else 0


def answers_settled(application) -> None:
    """Inside the staff transaction, with the application locked."""
    from .runs import enqueue_assessment

    application.refresh_from_db(fields=["stage"])
    if application.stage != Stage.AWAITING_ANSWERS:
        return
    if Question.objects.filter(application=application, approval_state=Question.Approval.APPROVED, status__in=OPEN).exists():
        return  # the round is not finished
    last = current_round(application)
    if last >= settings.CATALYST_ASSESSMENT_ROUNDS:
        transition(application.pk, (Stage.AWAITING_ANSWERS,), Stage.AWAITING_DECISION, event_kind="clarification_round_cap",
                   data={"round": last})
        return
    transition(application.pk, (Stage.AWAITING_ANSWERS,), Stage.ASSESSING, event_kind="answers_confirmed",
               data={"round": last + 1})
    why = []
    run = enqueue_assessment(application, "answers_confirmed", why=why, round=last + 1)
    if run is None:  # nothing new to assess (for example no answer was confirmed): staff decide
        transition(application.pk, (Stage.ASSESSING,), Stage.AWAITING_DECISION, event_kind="reassessment_not_queued",
                   data={"reason": why[0] if why else "unknown"})


def staff_round(application) -> int:
    """The round a staff-authored question belongs to: the current one, or the first."""
    return max(current_round(application), 1)
