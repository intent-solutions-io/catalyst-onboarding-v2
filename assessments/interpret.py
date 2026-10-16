"""The P3 reply interpreter (018 section 5.4; task 3B.3). It implements P2's `ReplyInterpreter` protocol
(`correspondence.processing`); there is no second interface. Test models only, through `agent.run_checked`.

What leaves Catalyst (018 5.2): the exact question texts as aliases (Q1..), and the reply's own text with quoted
material and our sent text removed, cleaned, scrubbed (contacts, links, names) and fenced. The model returns,
per question, an outcome and up to 10 verbatim quotes. Each quote must occur **exactly once** in the stored
derivative outside quoted ranges; the adapter turns it into a `Span`, and `validate_proposals` re-checks every
span. A quote that cannot be located (for example one that includes a redaction placeholder) is refused, with
one repair. The result is advice on a `ReplyInterpretation`; only staff confirm an outcome.

`admit` runs inside the handler's pre-call transaction: the model must be available and the shared daily
request budget (assessments and interpretations together) must allow one attempt.
"""

import secrets
from typing import Literal

from django.conf import settings
from django.db import connection
from django.db.models import Sum
from django.db.models.functions import Now, TruncDate
from pydantic import Field

from correspondence.models import InboundMessage, ReplyInterpretation
from correspondence.processing import (InterpretResult, InterpretUnavailable, Provenance, QuestionProposal, Span)
from correspondence.question_screen import unsafe

from . import agent, pack as packs, snapshot
from .models import AssessmentInvocation
from .schema import Strict

GLOBAL_LOCK = 0x43415441  # the same advisory lock as assessment budgets (runs._GLOBAL_LOCK)


class Answer(Strict):
    question_alias: str = Field(pattern=r"^Q[0-9]{1,2}$")
    outcome: Literal["satisfied", "partial", "not_addressed"]
    quotes: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=200)


class InterpretOutput(Strict):
    schema_version: Literal["1"]
    answers: list[Answer] = Field(min_length=1, max_length=20)


def daily_requests_used() -> int:
    """Requests reserved today by assessments and reply interpretations together (018 6)."""
    def today(model):
        return model.objects.annotate(day=TruncDate("started_at")).filter(day=TruncDate(Now())).aggregate(
            n=Sum("reserved_requests"))["n"] or 0
    return today(AssessmentInvocation) + today(ReplyInterpretation)


def _visible(text: str, quoted, sent: str) -> str:
    """The reply as the model may see it: quoted ranges and our own sent text removed (018 5.2)."""
    out, last = [], 0
    for span in sorted(quoted, key=lambda s: s.start):
        out.append(text[last:span.start])
        out.append("\n")
        last = max(last, span.end)
    out.append(text[last:])
    visible = "".join(out)
    return visible.replace(sent.strip(), "") if sent.strip() else visible


def _locate(quote: str, request) -> Span | None:
    """The one occurrence of `quote` in the stored derivative that lies outside quoted material."""
    if not quote.strip():
        return None
    found, start = [], request.text.find(quote)
    while start != -1:
        span = Span(start, start + len(quote))
        if not any(q.start < span.end and span.start < q.end for q in request.quoted):
            found.append(span)
        start = request.text.find(quote, start + 1)
    return found[0] if len(found) == 1 else None


class Interpreter:
    requests_per_attempt = 2  # the call and one repair (agent.run_checked)

    def admit(self, application) -> str:
        """A refusal code, or "" to proceed. Inside the pre-call transaction (lock order: application, then the
        advisory budget lock, then the action)."""
        try:
            agent.build_model()
        except agent.ModelUnavailable as exc:
            return str(exc)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [GLOBAL_LOCK])
        if daily_requests_used() + self.requests_per_attempt > settings.CATALYST_ASSESSMENT_DAILY_REQUESTS:
            return "daily_request_budget"
        return ""

    def interpret(self, request):
        try:
            pack = packs.load_text()
        except packs.PackRefused as exc:
            return InterpretUnavailable(str(exc))
        message = InboundMessage.objects.select_related("application").get(public_id=request.message_id)
        names = snapshot._names(message.application)
        aliases = {f"Q{n}": q for n, q in enumerate(request.questions, start=1)}
        nonce = secrets.token_hex(8)
        reply = snapshot._fence(snapshot.scrub(snapshot.clean(_visible(request.text, request.quoted, request.sent_body)), names))
        lines = ["QUESTIONS:"] + [f"{alias}: {snapshot._fence(snapshot.clean(q.text, one_line=True))}" for alias, q in aliases.items()]
        lines += ["", "REPLY:", f"<<DATA alias=R nonce={nonce}>>\n{reply}\n<</DATA nonce={nonce}>>"]

        def check(output: InterpretOutput) -> list[str]:
            found = []
            seen = [a.question_alias for a in output.answers]
            if sorted(seen) != sorted(aliases) or len(set(seen)) != len(seen):
                found.append("questions_do_not_match")
            for answer in output.answers:
                if unsafe(answer.note):
                    found.append("note_not_clean")
                if answer.outcome == "not_addressed" and answer.quotes:
                    found.append("not_addressed_with_quotes")
                if answer.outcome != "not_addressed" and not answer.quotes:
                    found.append("outcome_without_quotes")
                if any(_locate(q, request) is None for q in answer.quotes):
                    found.append("quote_not_found_once_outside_quoted_text")
            return sorted(set(found))
        try:
            outcome = agent.run_checked(pack.system, "\n".join(lines), InterpretOutput, check)
        except agent.ModelUnavailable as exc:
            return InterpretUnavailable(str(exc))
        except agent.InvalidOutput as exc:
            return InterpretUnavailable(exc.code)
        except agent.BudgetStop as exc:
            return InterpretUnavailable(str(exc))
        except agent.ProviderError as exc:
            return InterpretUnavailable(f"provider_{exc}")
        proposals = tuple(
            QuestionProposal(question_id=aliases[a.question_alias].id, outcome=a.outcome,
                             spans=tuple(_locate(q, request) for q in a.quotes), note=a.note.strip())
            for a in outcome.output.answers)
        provenance = Provenance(prompt_pack_version=pack.name, prompt_pack_sha256=pack.sha256, model_id=outcome.model_id[:100],
                                usage={"requests": outcome.requests, "input_tokens": outcome.input_tokens,
                                       "output_tokens": outcome.output_tokens},
                                quote_strip_version=1, text_sha256=request.text_sha256)
        return InterpretResult(proposals=proposals, provenance=provenance)
