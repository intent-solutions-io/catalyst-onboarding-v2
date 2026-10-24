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

oc4.9, the live-call protections (018 section 21), all in the one checked-run path the assessment and the reply
interpreter share:

- **approval before any live request:** `build_model(use)` asks `approval.require` for the owner's recorded approval
  of exactly this use whenever the model setting is anything but "none" or "test"; with no live branch, an approved
  use still ends `model_not_authorized`;
- **the approved fields bound to what is sent:** the request builders report the source fields they used, and a
  field outside `approval.FIELDS` (and, live, outside the recorded approval's terms) refuses (`fields_not_approved`);
- **the approval re-checked on every request** (a live model): the repair and any later caller included;
- **a lease fence before each request, the repair included:** every request goes through `_Guarded`, which first
  renews the claim's lease through the active `workflow.keeper.LeaseKeeper` (a heartbeat thread also renews it while
  a call outlives a third of the lease); a lost lease raises `ledger.LeaseLost` and no further request is made;
- **a provider-side timeout Catalyst enforces:** each request is bounded by
  `CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS` around the model call (and the same value goes to a provider client
  as its own timeout); a timeout is a provider error, never an adverse result. One attempt fits in half the lease
  (`config.guards.attempt_lease_problems`).
"""

import asyncio
from dataclasses import dataclass

from django.conf import settings
from django.db import connections
from pydantic_ai import Agent, ModelRetry, UsageLimits
from pydantic_ai import models as _models
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.wrapper import WrapperModel

from config import guards
from workflow import keeper as keepers, ledger

from . import approval
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


# Bounds a live model would also need (018 6); passed on every run so they are already exercised. The timeout is
# filled from CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS on every call (oc4.9).
MODEL_SETTINGS = {"max_tokens": 4000, "temperature": 0.0}


def build_model(use: "approval.Use | None" = None):
    if _models.ALLOW_MODEL_REQUESTS:  # nothing may switch the first layer back on
        raise ModelUnavailable("model_requests_enabled")
    mode = settings.CATALYST_ASSESSMENT_MODEL
    if mode == "test" and guards.synthetic(settings.CATALYST_ENV):
        model = TEST_MODEL if TEST_MODEL is not None else TestModel()
        if not isinstance(model, (TestModel, FunctionModel)):
            raise ModelUnavailable("model_not_a_test_model")
        return model
    if mode not in ("none", "test"):  # a live value: the owner's recorded approval of this exact use first (oc4.9)
        if use is None:
            raise ModelUnavailable("model_use_not_approved")
        try:
            approval.require(use)
        except approval.NotApproved as exc:
            raise ModelUnavailable(str(exc)) from None
    raise ModelUnavailable("model_not_authorized")  # no live branch exists: an approval is necessary, never sufficient


class _Guarded(WrapperModel):
    """Every request, the repair included (oc4.9): the approval re-check (a live model only) and the lease fence first,
    each in a worker thread (the ORM may not run on the event loop) and each bounded by the request timeout, then the
    model call bounded by the same timeout, then a worker-alive beat from the calling side. A fence that cannot
    confirm the lease in time counts as a lost lease; an approval re-check that cannot finish in time refuses. Streaming
    is refused: nothing here uses it, and it would bypass the bound on the response."""

    def __init__(self, wrapped, *, fence, check, after, timeout: float):
        super().__init__(wrapped)
        self.fence, self.check, self.after, self.timeout = fence, check, after, timeout

    async def request(self, messages, model_settings, model_request_parameters):
        if self.check is not None:
            try:
                await asyncio.wait_for(asyncio.to_thread(self.check), timeout=self.timeout)
            except TimeoutError:
                raise approval.NotApproved("approval_check_timeout") from None
        if self.fence is not None:
            try:
                await asyncio.wait_for(asyncio.to_thread(self.fence), timeout=self.timeout)
            except TimeoutError:
                raise ledger.LeaseLost from None
        response = await asyncio.wait_for(self.wrapped.request(messages, model_settings, model_request_parameters),
                                          timeout=self.timeout)
        if self.after is not None:
            self.after()
        return response

    def request_stream(self, *args, **kwargs):
        raise ModelUnavailable("streaming_not_allowed")


def _recheck(use, fields):
    """Per request, for a live model: the approval still stands for this use, and names every field being sent."""
    def check():
        try:
            record = approval.require(use)
            if not set(fields) <= set((record.terms or {}).get("fields") or ()):
                raise approval.NotApproved("fields_not_approved")
        finally:
            connections.close_all()  # always a worker thread: close the connection it opened
    return check


def _usage(result):
    usage = result.usage() if callable(result.usage) else result.usage  # a property in 2.55 (DEMONSTRATED)
    return (getattr(usage, "requests", 0) or 0, getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0)


def attempt_tokens() -> int:
    """The most one attempt may spend: two requests' input plus the attempt's output (018 6)."""
    return 2 * settings.CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST + settings.CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT


def run_checked(system: str, prompt: str, output_type, check, use: "approval.Use | None" = None,
                fields: frozenset | None = None) -> Outcome:
    """One bounded attempt: at most 2 requests (the call and one repair). `check(output)` returns problem codes;
    any code triggers the one repair (ModelRetry), and a second failure ends the attempt as invalid output.
    Shared by the assessment and the reply interpreter, so the live-model refusal, the approval check, the lease
    fence, the timeout and the limits exist once. Raises `ledger.LeaseLost` when the claim's lease is lost before a
    request: nothing further is requested and nothing is recorded by this attempt.

    `fields` is the set of source fields the request builder actually used (`snapshot.Request.fields`,
    `interpret.build_prompt`); with a `use`, the call is refused (`fields_not_approved`) unless every one is in the
    approved field list for the purpose, and, for a live model, in the recorded approval's terms on every request. A
    model other than a test model is refused without an active lease keeper (`no_lease_fence`)."""
    if use is not None and (fields is None or not set(fields) <= set(approval.FIELDS.get(use.purpose, ()))):
        raise ModelUnavailable("fields_not_approved")
    model = build_model(use)
    keeper = keepers.current()
    live = not isinstance(model, (TestModel, FunctionModel))
    if live and keeper is None:
        raise ModelUnavailable("no_lease_fence")  # never skipped silently: a live call always runs fenced
    if live and use is None:
        raise ModelUnavailable("model_use_not_approved")
    timeout = float(settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS)
    guarded = _Guarded(model, fence=keeper.fence if keeper is not None else None,
                       check=_recheck(use, fields or frozenset()) if live else None,
                       after=None, timeout=timeout)
    agent = Agent(guarded, output_type=output_type, system_prompt=system, retries=approval.REPAIR_LIMIT)

    last = []

    @agent.output_validator
    def validate(output):
        found = check(output)
        last[:] = found
        if found:
            raise ModelRetry("The output broke these rules; fix them and answer again: " + ", ".join(found))
        return output

    limits = UsageLimits(request_limit=2, tool_calls_limit=2,
                         per_request_input_tokens_limit=settings.CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST,
                         output_tokens_limit=settings.CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT,
                         total_tokens_limit=attempt_tokens())
    try:
        result = agent.run_sync(prompt, usage_limits=limits, model_settings={**MODEL_SETTINGS, "timeout": timeout})
    except ledger.LeaseLost:
        raise
    except approval.NotApproved as exc:
        raise ModelUnavailable(str(exc)) from None
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


def assess(request, use: "approval.Use | None" = None) -> Outcome:
    return run_checked(request.system, request.prompt, AssessmentOutput, lambda output: problems(output, request), use,
                       fields=request.fields)
