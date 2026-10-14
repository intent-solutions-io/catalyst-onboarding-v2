"""The PydanticAI assessment agent (018 5.5, 5.6, 6; task 3B.2). Test models only.

Live model use is refused in three layers (018 5.5): `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` is set in
the app's `ready()` for every environment; `build_model` has no live branch at all (no provider client is even
installed: the dependency is `pydantic-ai-slim` without a provider extra) and returns a test model only when
`CATALYST_ASSESSMENT_MODEL == "test"` in the `test` environment; and `config.guards.assessment_problems` refuses
any other value at start-up. Agent instrumentation is never enabled.

One attempt = at most 2 model requests (the call and one repair, `retries=1`): an output that fails
`schema.problems` raises `ModelRetry` once, then `UnexpectedModelBehavior` ends the attempt as invalid output.
SDK and transport retries do not exist here (no provider client); the ledger's attempt bound is the only other
retry layer, so the requests per snapshot are bounded by 2 x the attempt bound (018 6).
"""

from dataclasses import dataclass

from django.conf import settings
from pydantic_ai import Agent, ModelRetry, UsageLimits
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.test import TestModel

from .schema import AssessmentOutput, problems

TEST_MODEL = None  # a test may set a FunctionModel here; otherwise TestModel is used (test environment only)


class ModelUnavailable(Exception):
    """No model may be used here; the message is a reason code."""


class InvalidOutput(Exception):
    pass


class BudgetStop(Exception):
    pass


class ProviderError(Exception):
    """A failure of the model call itself (transient by default)."""


@dataclass(frozen=True)
class Outcome:
    output: AssessmentOutput
    requests: int
    input_tokens: int
    output_tokens: int
    model_id: str


def build_model():
    if settings.CATALYST_ASSESSMENT_MODEL == "test" and settings.CATALYST_ENV == "test":
        return TEST_MODEL if TEST_MODEL is not None else TestModel()
    raise ModelUnavailable("model_not_authorized")


def _usage(result):
    usage = result.usage() if callable(result.usage) else result.usage  # a property in 2.55 (DEMONSTRATED)
    return (getattr(usage, "requests", 0) or 0, getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0)


def assess(request) -> Outcome:
    model = build_model()
    agent = Agent(model, output_type=AssessmentOutput, system_prompt=request.system, retries=1)

    @agent.output_validator
    def check(output: AssessmentOutput) -> AssessmentOutput:
        found = problems(output, request)
        if found:
            raise ModelRetry("The output broke these rules; fix them and answer again: " + ", ".join(found))
        return output

    limits = UsageLimits(request_limit=2, per_request_input_tokens_limit=settings.CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST,
                         output_tokens_limit=settings.CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT,
                         total_tokens_limit=settings.CATALYST_ASSESSMENT_TOTAL_TOKENS_PER_SNAPSHOT)
    try:
        result = agent.run_sync(request.prompt, usage_limits=limits)
    except UsageLimitExceeded:
        raise BudgetStop("usage_limit_exceeded") from None
    except UnexpectedModelBehavior:
        raise InvalidOutput("invalid_output_after_repair") from None
    except (ModelUnavailable, InvalidOutput, BudgetStop):
        raise
    except Exception as exc:  # the provider call itself failed (error, timeout); never an adverse result
        raise ProviderError(type(exc).__name__) from None
    requests, input_tokens, output_tokens = _usage(result)
    return Outcome(result.output, requests, input_tokens, output_tokens, getattr(model, "model_name", type(model).__name__))
