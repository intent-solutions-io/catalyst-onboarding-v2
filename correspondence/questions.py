"""Clarification questions for P3 (018 section 4 steps 5, 6 and 8; section 15; 019 section 5; task 3B.3).

- `create_question`: the one way a P3 question comes into existence, model-proposed or staff-authored. The caller
  holds the application lock. Every question passes the same screen (`question_screen`), names the criterion and
  the evidence gap it addresses, may offer an alternative evidence route, and is deduplicated by normalized text
  per application. It is stored `proposed`: nothing is sent until an operator approves it (P2
  `approve_question`, P3-D-5).
- `author_question`: the staff service behind the P3 authoring screen.
- `answers_settled`: called after staff confirm an outcome or withdraw a question; it hands over to the
  assessment app through the code-fixed seam `CATALYST_ANSWERS_CONFIRMED_HOOK` (the `CATALYST_ATTENTION_OPENER`
  pattern), so `correspondence` never imports `assessments` (003 ADR-01).
"""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.module_loading import import_string

from applications.models import TERMINAL_STAGES, Application, ApplicationEvent

from .common import Refused, actor_ref, require
from .models import Question
from .question_screen import question_problems, text_key, unsafe
from .staff_items import event

GAP_LIMIT = 300
TEXT_LIMIT = 400


def create_question(application, *, text: str, origin: str, criterion_id: str, evidence_gap: str,
                    alternative_route: str = "", requires_evidence: bool = False, raised_by: str = "", round: int = 0,
                    actor: str = "", actor_type=ApplicationEvent.ActorType.SYSTEM):
    """Returns the new question, or None when a live question with the same normalized text exists."""
    text, evidence_gap, alternative_route = text.strip(), evidence_gap.strip(), alternative_route.strip()
    if question_problems(text) or len(text) > TEXT_LIMIT:
        raise Refused("question_refused")
    if not criterion_id or len(criterion_id) > 40:
        raise Refused("question_needs_a_criterion")
    if not evidence_gap or len(evidence_gap) > GAP_LIMIT or unsafe(evidence_gap):
        raise Refused("question_needs_an_evidence_gap")
    if len(alternative_route) > GAP_LIMIT or unsafe(alternative_route):
        raise Refused("alternative_route_refused")
    key = text_key(text)
    if Question.objects.filter(application=application, text_key=key).exclude(status=Question.Status.WITHDRAWN).exists():
        return None
    try:
        with transaction.atomic():
            question = Question.objects.create(
                application=application, text=text, origin=origin, criterion_id=criterion_id, evidence_gap=evidence_gap,
                alternative_route=alternative_route, requires_evidence=requires_evidence, raised_by=raised_by,
                round=round, text_key=key)
    except IntegrityError:
        return None  # a concurrent duplicate won
    event(application, "question_proposed" if origin == Question.Origin.MODEL else "question_authored",
          {"question": str(question.public_id), "criterion": criterion_id, "round": round, "raised_by": raised_by},
          actor_type=actor_type, actor_ref=actor)
    return question


def author_question(application_id: int, user, *, text: str, criterion_id: str, evidence_gap: str,
                    alternative_route: str = "", requires_evidence: bool = False, round: int = 0,
                    stages: tuple = ()) -> Question:
    """018 step 6: staff write a question; it is stored proposed and still needs P2 approval to be sent. `stages`,
    when given, is checked under the application lock."""
    require(user, "author_question")
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        if application.stage in TERMINAL_STAGES:
            raise Refused("application_closed")
        if stages and application.stage not in stages:
            raise Refused("stage_not_clarifying")
        question = create_question(
            application, text=text, origin=Question.Origin.STAFF, criterion_id=criterion_id, evidence_gap=evidence_gap,
            alternative_route=alternative_route, requires_evidence=requires_evidence, raised_by="staff", round=round,
            actor=actor_ref(user), actor_type=ApplicationEvent.ActorType.STAFF)
        if question is None:
            raise Refused("duplicate_question")
    return question


def answers_settled(application) -> None:
    """Inside the caller's transaction, with the application locked."""
    hook = getattr(settings, "CATALYST_ANSWERS_CONFIRMED_HOOK", None)
    if hook:
        import_string(hook)(application)


def sent_text(question) -> str:
    """What the applicant reads (019 section 5, D-35): the question and, where one exists, the alternative
    evidence route, so a person with confidential or private work is offered another way. Both were screened when
    the question was created; P2 questions have no route and are sent unchanged."""
    if not question.alternative_route:
        return question.text
    return f"{question.text}\n\nIf you cannot share that, you could instead: {question.alternative_route}"
