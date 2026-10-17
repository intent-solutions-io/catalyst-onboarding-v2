"""The authorized qualification decision (018 section 4 step 9, section 7; P3 3B.4; D-34 P3-D-9 to P3-D-11 and
P3-D-16; D-35: per-criterion rationale, the selection-policy reference, and the human-only assessment path).

`record_decision` is one transaction with the application locked. It refuses unless:

- **authority** is configured: `CATALYST_QUALIFICATION_AUTHORITY` is fixed in code and is `None` until POL-05 is
  recorded; while it is `None` everyone is refused, superusers included (TEST-P3-04). Once set, the actor must be
  an authenticated, active, non-superuser human holding `assessments.record_qualification_decision` by explicit
  grant (no group carries it);
- **what the decision-maker saw is still true**: the decision digest shown on the screen (the current snapshot
  manifest, the clarification question set, and the run relied on) equals the one recomputed now (TEST-P3-51);
- **the assessment is valid**: the latest succeeded run is on the current snapshot (a re-fetch or a newly confirmed
  answer makes it stale: reassess first), no run is in flight and no evidence item is pending; or, when model
  advice is unavailable for this snapshot or suspended, a **recorded human-only assessment** (D-35) with a reason;
- **the stage** is compare-and-set from `awaiting_decision` (or from `assessing` for a human-only assessment after
  a failed run); no identity-affecting staff item is open; `admit` is refused while automation is paused;
- **every rubric criterion** has a human rationale with capability and strength of evidence recorded separately.

Then: the `QualificationDecision` row, the stage move (`admitted`, `declined` or `on_hold`), an event, and one
held follow-on for P4 (`issue_nda:<application>` for admit, `send_decline:<application>` for decline; nothing for
hold). A database trigger refuses any move into a decided stage without a decision row inserted in the same
transaction (TEST-P3-52). No model output is read to choose anything here.
"""

import hashlib
import json
import re

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from applications.models import Application, ApplicationEvent, Stage
from applications.stages import StageConflict, transition
from correspondence.models import Question, StaffItem
from correspondence.processing import RESOLUTIONS
from correspondence.common import Refused as NoteRefused
from correspondence.staff_items import clean_note as _clean_note
from workflow.models import AutomationPause, PendingAction

from . import pack as packs, snapshot
from .models import AssessmentRun, EvidenceItem, QualificationDecision
from .services import Refused

STAGE_FOR = {"admit": Stage.ADMITTED, "decline": Stage.DECLINED, "hold": Stage.ON_HOLD}
FOLLOW_ON = {"admit": "issue_nda", "decline": "send_decline"}  # held; P4 and POL-06 release them
CAPABILITY = ("shown", "partly_shown", "not_shown", "unknown")
EVIDENCE_STRENGTH = ("strong", "moderate", "weak", "none")
FAILED = ("refused", "invalid_output", "failed", "capped", "abandoned")
_REASON_CODE = re.compile(r"^[a-z][a-z_]{2,39}$")
# Staff items that concern who the applicant is: a decision waits until they are resolved (018 section 7).
IDENTITY_ITEMS = tuple(code for code, resolutions in RESOLUTIONS.items()
                       if "resolve_identity_exception" in resolutions.values())


def clean_note(text: str) -> str:
    try:
        return _clean_note(text)
    except NoteRefused as exc:
        raise Refused(str(exc)) from None


def can_decide(user) -> bool:
    return (settings.CATALYST_QUALIFICATION_AUTHORITY is not None and user is not None and user.is_authenticated
            and user.is_active and not user.is_superuser and user.has_perm("assessments.record_qualification_decision"))


def policy_ref(pack) -> str:
    """The selection policy the decision applies (019 section 6). Until an approved policy is activated, the
    synthetic rubric stands in, and the reference says so."""
    return settings.CATALYST_SELECTION_POLICY or f"none-approved:{pack.name}:rubric-{pack.rubric_version}"


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def latest_run(application):
    return AssessmentRun.objects.filter(application=application).order_by("-id").first()


def decision_state(application) -> dict:
    """What a decision would rely on now: the current snapshot, the run (if valid), the open question set and the
    digest that binds them. The screen shows `digest`; the service recomputes it."""
    run = latest_run(application)
    pack_name = run.prompt_pack if run is not None else packs.CURRENT
    try:
        pack = packs.load(pack_name)
    except packs.PackRefused:
        pack = None
    manifest = snapshot.manifest(application, pack) if pack is not None else None
    current = snapshot.snapshot_sha256(manifest) if manifest is not None else ""
    succeeded = (AssessmentRun.objects.filter(application=application, status="succeeded", snapshot_sha256=current)
                 .order_by("-id").first()) if current else None
    questions = sorted([str(q), s, a] for q, s, a in Question.objects.filter(application=application).exclude(round=0)
                       .values_list("public_id", "status", "approval_state"))
    human_only_allowed = succeeded is None and (
        settings.CATALYST_ASSESSMENT_MODEL == "none"  # model advice suspended or not configured
        or (run is not None and run.snapshot_sha256 == current and run.status in FAILED))
    return {"pack": pack, "manifest": manifest, "snapshot": current, "run": succeeded, "latest_run": run,
            "questions": questions, "human_only_allowed": human_only_allowed,
            "digest": _sha({"snapshot": current, "questions": questions,
                            "run": str(succeeded.public_id) if succeeded else ""})}


def _rationale(pack, rationale: dict) -> dict:
    ids = [c["id"] for c in pack.criteria]
    if not isinstance(rationale, dict) or sorted(rationale) != sorted(ids):
        raise Refused("rationale_needed_for_every_criterion")
    out = {}
    for criterion in ids:
        entry = rationale[criterion] or {}
        if entry.get("capability") not in CAPABILITY or entry.get("evidence_strength") not in EVIDENCE_STRENGTH:
            raise Refused("rationale_needs_capability_and_evidence_strength")
        note = clean_note(str(entry.get("note", "")))
        if not note:
            raise Refused("rationale_needs_a_note")
        out[criterion] = {"capability": entry["capability"], "evidence_strength": entry["evidence_strength"], "note": note}
    return out


def record_decision(application_id: int, user, *, outcome: str, reason_code: str, reason_text: str = "",
                    expected_digest: str, rationale: dict, human_only_reason: str = "") -> QualificationDecision:
    if settings.CATALYST_QUALIFICATION_AUTHORITY is None:
        raise Refused("no_decision_authority_configured")  # POL-05: everyone, superusers included
    if not can_decide(user):
        raise PermissionDenied("record_qualification_decision")
    if outcome not in STAGE_FOR:
        raise Refused("unknown_outcome")
    if not _REASON_CODE.match(reason_code or ""):
        raise Refused("reason_code_invalid")
    reason_text = clean_note(reason_text)
    human_only = bool(human_only_reason.strip())
    human_only_reason = clean_note(human_only_reason)[:300] if human_only else ""
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        state = decision_state(application)
        if state["pack"] is None or state["manifest"] is None:
            raise Refused("no_snapshot")
        if expected_digest != state["digest"]:
            raise Refused("changed_since_shown")  # a re-fetch, a confirmed answer, a question set change, a new run
        if AssessmentRun.objects.filter(application=application, status__in=("queued", "reserved")).exists():
            raise Refused("assessment_in_flight")
        version = application.versions.get(public_id=state["manifest"]["version"])
        if EvidenceItem.objects.filter(application=application, adopted_version=version, status="pending").exists():
            raise Refused("evidence_pending")
        if human_only:
            if not state["human_only_allowed"]:
                raise Refused("human_only_assessment_not_allowed")  # never a shortcut past a working assessment
            run, from_stages = None, (Stage.AWAITING_DECISION, Stage.ASSESSING)
        else:
            run = state["run"]
            if run is None:
                raise Refused("no_valid_assessment")  # P3-D-10: rerun, or reassess after new evidence or answers
            from_stages = (Stage.AWAITING_DECISION,)
        if application.stage not in from_stages:
            raise Refused("stage_not_decidable")
        if StaffItem.objects.filter(application=application, status="open", reason_code__in=IDENTITY_ITEMS).exists():
            raise Refused("identity_item_open")
        if outcome == "admit" and AutomationPause.objects.filter(subject_type="application",
                                                                 subject_id=application.public_ref).exists():
            raise Refused("admit_refused_while_paused")
        checked = _rationale(state["pack"], rationale)
        try:
            with transaction.atomic():
                decision = QualificationDecision.objects.create(
                    application=application, adopted_version=version, run=run, outcome=outcome,
                    basis=QualificationDecision.Basis.HUMAN_ONLY if human_only else QualificationDecision.Basis.MODEL_ASSISTED,
                    human_only_reason=human_only_reason, reason_code=reason_code, reason_text=reason_text,
                    rationale=checked, snapshot_sha256=state["snapshot"], decision_digest=state["digest"],
                    policy_ref=policy_ref(state["pack"]), actor_ref=actor)
        except IntegrityError:
            raise Refused("already_decided") from None  # one admit or decline per application (TEST-P3-45)
        try:
            transition(application.pk, from_stages, STAGE_FOR[outcome], event_kind=f"qualification_{outcome}",
                       data={"decision": str(decision.public_id), "basis": decision.basis, "policy": decision.policy_ref},
                       actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
        except StageConflict:
            raise Refused("stage_not_decidable") from None
        kind = FOLLOW_ON.get(outcome)
        if kind:
            PendingAction.objects.create(kind=kind, subject_type="application", subject_id=application.public_ref,
                                         input_ref=str(decision.public_id), idempotency_key=f"{kind}:{application.public_ref}",
                                         status=PendingAction.Status.HELD)
    return decision
