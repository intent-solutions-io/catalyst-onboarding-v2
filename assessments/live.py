"""The live model branch (parity track bgl.12; 034 section 2.2 row 15; 018 5.5 and 21): MiniMax through PydanticAI's
OpenAI-compatible chat model. Built beside, not over, the recorded decisions: D-53 ("no model" for wave one), the
launch-wide suspension of model advice (011 section 4.1) and oc4.9 all hold at the default configuration, because
every switch below is off in code and refused in a live environment.

The branch is reached only when all of these hold, in this order (`agent.build_model`):

1. `CATALYST_ASSESSMENT_LIVE_ACTIVATION` (fixed in code, 0) is on, and the environment is synthetic (`test`,
   `staging`): `config.guards.assessment_problems` refuses a live model value, a base URL, a key or the activation
   anywhere else, so production cannot be configured into this branch;
2. `CATALYST_ASSESSMENT_MODEL` names a live model as `<provider>:<model id>` (`approval.parse_model`);
3. the owner's recorded approval of exactly this use stands (`approval.require`), re-checked before every request;
4. the base URL (`CATALYST_ASSESSMENT_LIVE_BASE_URL`) and the key (the secret `CATALYST_ASSESSMENT_API_KEY`) are set;
5. `pydantic_ai.models.ALLOW_MODEL_REQUESTS` has been switched on by `allow_requests()`, which only the worker entry
   point calls, and which itself requires 1, 2 and 4. The web process never calls it, so it never holds a model.

The client is `openai.AsyncOpenAI` over the configured base URL with zero SDK retries (the ledger's attempt bound is
the only retry layer, 018 6) and the Catalyst request timeout as the client's own; PydanticAI's `OpenAIChatModel`
(Chat Completions, tool output) runs over it. The first generation used the same provider through the same kind of
endpoint; the model name and base URL are settings here, never literals, and no key is read by anything but the
settings module. `openai` is imported in this module and nowhere else in `assessments` (tests/test_assessment.py pins
that), and the dependency uses httpx2, which the test-time raising transport refuses (tests/conftest.py).

The live evaluation itself, under a budget and the owner's approval, is bead oc4.7 and is not run by this code.
"""

from urllib.parse import urlsplit

from django.conf import settings
from pydantic_ai import models as _models
from pydantic_ai.exceptions import ModelHTTPError

from config import guards

from . import approval

PROVIDER = "minimax"  # the one provider this branch builds; any other name is refused (provider_not_supported)


def named():
    """The live model the setting names as (provider, model id), or None for "none", "test" and malformed values."""
    return approval.parse_model(settings.CATALYST_ASSESSMENT_MODEL)


def activated() -> bool:
    """The live activation is on and the environment is one that may hold it (test, staging)."""
    return int(getattr(settings, "CATALYST_ASSESSMENT_LIVE_ACTIVATION", 0) or 0) >= 1 and guards.synthetic(settings.CATALYST_ENV)


def base_url_problem(url: str) -> str:
    """"" when the base URL is usable: https to a named host, or http to a loopback literal (a fake in staging)."""
    parts = urlsplit(url or "")
    if not parts.hostname or parts.query or parts.fragment:
        return "live_base_url_invalid"
    if parts.scheme == "https":
        return ""
    if parts.scheme == "http" and guards.is_loopback_literal(parts.hostname):
        return ""
    return "live_base_url_not_https"


def configured() -> str:
    """A refusal code, or "" when the branch has everything it needs apart from the approval and the request flag."""
    model = named()
    if model is None:
        return "model_not_authorized"
    if model[0] != PROVIDER:
        return "provider_not_supported"
    problem = base_url_problem(getattr(settings, "CATALYST_ASSESSMENT_LIVE_BASE_URL", ""))
    if problem:
        return problem
    if not getattr(settings, "CATALYST_ASSESSMENT_API_KEY", ""):
        return "live_api_key_missing"
    return ""


def allow_requests() -> bool:
    """The worker entry point's one switch of PydanticAI's request flag: on only under the activation, in a synthetic
    environment, with a live model named and configured. Returns whether requests are allowed afterwards."""
    if activated() and configured() == "":
        _models.ALLOW_MODEL_REQUESTS = True
    return bool(_models.ALLOW_MODEL_REQUESTS)


def build(provider: str, model_id: str, timeout: float):
    """The live model for an approved, configured use. Imported lazily: the provider client loads only on this path."""
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    if provider != PROVIDER:
        raise ValueError("provider_not_supported")
    client = AsyncOpenAI(base_url=settings.CATALYST_ASSESSMENT_LIVE_BASE_URL, api_key=settings.CATALYST_ASSESSMENT_API_KEY,
                         max_retries=0, timeout=timeout)
    return OpenAIChatModel(model_id, provider=OpenAIProvider(openai_client=client))


def transport_errors() -> tuple:
    """The provider client's failures, all of them a failed call and never an adverse result (018 6): connection,
    timeout and status errors from the client, and PydanticAI's own wrapping of a status error."""
    from openai import APIConnectionError, APIStatusError, APITimeoutError

    return (APIConnectionError, APITimeoutError, APIStatusError, ModelHTTPError)
