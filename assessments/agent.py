"""The PydanticAI assessment agent (018 5.5, 5.6, 6; task 3B.2). Test models only.

Live model use is refused in three layers (018 5.5): `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` is set when
this module is imported, which is the only way any code reaches a model (it costs about 2 s to import, so it is not
done in every process's `ready()`); `build_model` has no live branch at all (no provider client is even
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
from pydantic_ai import models as _models
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from .schema import AssessmentOutput, problems

_models.ALLOW_MODEL_REQUESTS = False  # 018 5.5, first layer: no request to a non-test model, in any environment

TEST_MODEL = None  # a test may set a FunctionModel here; otherwise TestModel is used (test environment only)


class ModelUnavailable(Exception):
    """No model may be used here; the message is a reason code."""


class InvalidOutput(Exception):
    def __init__(self, code: str, problems=()):
        super().__init__(code)
        self.code, self.problems = code, list(problems)  # fixed reason codes only, never model text


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
    provider: str = "test"  # only test models exist (018 5.5)
    output_mode: str = "tool"  # the default output mode for a pydantic output type


# Bounds a live model would also need (018 6); passed on every run so they are already exercised.
MODEL_SETTINGS = {"max_tokens": 4000, "temperature": 0.0, "timeout": 60}


def build_model():
    if _models.ALLOW_MODEL_REQUESTS:  # nothing may switch the first layer back on
        raise ModelUnavailable("model_requests_enabled")
    if settings.CATALYST_ASSESSMENT_MODEL == "test" and settings.CATALYST_ENV == "test":
        model = TEST_MODEL if TEST_MODEL is not None else TestModel()
        if not isinstance(model, (TestModel, FunctionModel)):
            raise ModelUnavailable("model_not_a_test_model")
        return model
    raise ModelUnavailable("model_not_authorized")


def _usage(result):
    usage = result.usage() if callable(result.usage) else result.usage  # a property in 2.55 (DEMONSTRATED)
    return (getattr(usage, "requests", 0) or 0, getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0)


def attempt_tokens() -> int:
    """The most one attempt may spend: two requests' input plus the attempt's output (018 6)."""
    return 2 * settings.CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST + settings.CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT


def assess(request) -> Outcome:
    model = build_model()
    agent = Agent(model, output_type=AssessmentOutput, system_prompt=request.system, retries=1)

    last = []

    @agent.output_validator
    def check(output: AssessmentOutput) -> AssessmentOutput:
        found = problems(output, request)
        last[:] = found
        if found:
            raise ModelRetry("The output broke these rules; fix them and answer again: " + ", ".join(found))
        return output

    limits = UsageLimits(request_limit=2, tool_calls_limit=2,
                         per_request_input_tokens_limit=settings.CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST,
                         output_tokens_limit=settings.CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT,
                         total_tokens_limit=attempt_tokens())
    try:
        result = agent.run_sync(request.prompt, usage_limits=limits, model_settings=MODEL_SETTINGS)
    except UsageLimitExceeded:
        raise BudgetStop("usage_limit_exceeded") from None
    except UnexpectedModelBehavior as exc:
        code = "invalid_output_after_repair" if "retries" in str(exc).lower() else "unexpected_model_behavior"
        raise InvalidOutput(code, last) from None
    except (ModelUnavailable, InvalidOutput, BudgetStop):
        raise
    except RuntimeError as exc:
        if "ALLOW_MODEL_REQUESTS" in str(exc):
            raise ModelUnavailable("model_requests_disabled") from None
        raise ProviderError(type(exc).__name__) from None
    except (OSError, TimeoutError) as exc:  # the provider call itself failed; never an adverse result
        raise ProviderError(type(exc).__name__) from None
    requests, input_tokens, output_tokens = _usage(result)
    return Outcome(result.output, requests, input_tokens, output_tokens, getattr(model, "model_name", type(model).__name__))
