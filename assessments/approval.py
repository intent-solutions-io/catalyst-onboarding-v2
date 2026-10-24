"""The pre-call approval check (oc4.9; 018 section 21): no live model request without the owner's recorded approval
of exactly what that request would be.

An approval (`ModelUseApproval`, written only by the owner-run `approve_model_use` command) names, for one purpose
(`assessment` or `interpretation`, which share the checked-run path and the daily budget), the **terms** below.
`require(use)` recomputes the terms for the call at hand and refuses unless the latest record for the purpose is an
approval whose digest is the same:

- `model_use_not_approved`: no record, or the latest one is a revocation;
- `model_use_approval_stale`: anything in the terms changed since the approval (the provider or model id, the field
  list, the pack or its digest, the rubric or schema version, a budget, the timeout, the repair limit), or the run
  was frozen under a pack other than the approved one (a stale snapshot);
- `model_not_authorized`: the model setting names no provider and model id.

The check runs before any reservation (the run's and the interpreter's pre-call) and again inside the checked run,
just before the model is used. Test models make no live request and need no approval. The live branch itself does
not exist yet (`agent.build_model`): an approval is necessary, never sufficient.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from django.conf import settings

REPAIR_LIMIT = 1  # one output repair per attempt (agent.run_checked: retries=REPAIR_LIMIT)
REQUESTS_PER_ATTEMPT = 1 + REPAIR_LIMIT
INTERPRET_SCHEMA_VERSION = "1"  # interpret.InterpretOutput.schema_version
PURPOSES = ("assessment", "interpretation")

# The exact fields that may leave Catalyst for each purpose (018 section 5.2), as the request builders send them:
# `snapshot._claim_texts` and `snapshot.build_request` for the assessment, `interpret.Interpreter.interpret` for the
# reply interpreter. A change to what is sent must change this list, which makes every approval stale.
FIELDS = {
    "assessment": (
        "claims.work[].note", "claims.contribution", "claims.experience", "claims.confidential_description",
        "claims.credentials[].name", "claims.credentials[].issuer",
        "confirmed_answers[].question_texts", "confirmed_answers[].outcomes", "confirmed_answers[].reply_own_text",
        "evidence_captures[].derived_text", "evidence_captures[].names_applicant", "evidence_captures[].truncated",
        "evidence_captures[].outcome", "missing_evidence[].claim_status", "rubric.criteria[].definition",
    ),
    "interpretation": ("questions[].text", "reply.derived_text_outside_quoted_and_own_text"),
}
BUDGETS = (
    "CATALYST_ASSESSMENT_ATTEMPTS", "CATALYST_ASSESSMENT_REQUESTS_PER_SNAPSHOT", "CATALYST_ASSESSMENT_RUNS_PER_APPLICATION",
    "CATALYST_ASSESSMENT_TOKENS_PER_APPLICATION", "CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST",
    "CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT", "CATALYST_ASSESSMENT_CONCURRENT_RUNS",
    "CATALYST_ASSESSMENT_DAILY_REQUESTS", "CATALYST_INTERPRETATION_DAILY_REQUESTS_PER_APPLICATION",
)
_PROVIDER = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class NotApproved(Exception):
    """The message is a reason code."""


@dataclass(frozen=True)
class Use:
    """What one live call would rely on: its purpose and the versions it was built from."""
    purpose: str
    pack: str
    pack_sha256: str
    rubric_version: int | None
    schema_version: str

    @classmethod
    def for_run(cls, run) -> "Use":
        """The run's own frozen versions, so a run frozen under another pack never matches a newer approval."""
        return cls("assessment", run.prompt_pack, run.prompt_pack_sha256, run.rubric_version, run.schema_version)

    @classmethod
    def current(cls, purpose: str) -> "Use":
        """The versions the code would use now (the command records these; the interpreter's pre-call checks them)."""
        from . import pack as packs

        if purpose == "assessment":
            from .schema import SCHEMA_VERSION

            pack = packs.load(packs.CURRENT)
            return cls(purpose, pack.name, pack.sha256, pack.rubric_version, SCHEMA_VERSION)
        pack = packs.load_text()
        return cls("interpretation", pack.name, pack.sha256, None, INTERPRET_SCHEMA_VERSION)


def parse_model(value: str):
    """`<provider>:<model id>` names a live model; anything else ("none", "test") names none. Returns the pair or None."""
    provider, sep, model_id = (value or "").partition(":")
    if not sep or not _PROVIDER.match(provider) or not _MODEL_ID.match(model_id):
        return None
    return provider, model_id


def terms(use: Use, provider: str, model_id: str) -> dict:
    if use.purpose not in PURPOSES:
        raise NotApproved("model_use_purpose_unknown")
    return {"purpose": use.purpose, "provider": provider, "model_id": model_id, "fields": list(FIELDS[use.purpose]),
            **{k: v for k, v in asdict(use).items() if k != "purpose"},
            "budgets": {name: getattr(settings, name) for name in BUDGETS},
            "request_timeout_seconds": float(settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS),
            "repair_limit": REPAIR_LIMIT, "requests_per_attempt": REQUESTS_PER_ATTEMPT}


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require(use: Use):
    """The approval this live call stands on, or NotApproved with a reason code (module docstring)."""
    from .models import ModelUseApproval

    named = parse_model(settings.CATALYST_ASSESSMENT_MODEL)
    if named is None:
        raise NotApproved("model_not_authorized")
    latest = ModelUseApproval.objects.filter(purpose=use.purpose).order_by("-id").first()
    if latest is None or latest.action != ModelUseApproval.Action.APPROVE:
        raise NotApproved("model_use_not_approved")
    if latest.terms_sha256 != digest(terms(use, *named)):
        raise NotApproved("model_use_approval_stale")
    return latest
