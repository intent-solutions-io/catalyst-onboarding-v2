"""The authorized qualification decision (018 section 4 step 9, section 7; P3 3B.4; D-34 P3-D-9 to P3-D-11 and
P3-D-16; D-35: per-criterion rationale, the selection-policy reference, and the human-only assessment path).

`record_decision` is one transaction with the application locked. It refuses unless:

- **authority** is configured: `CATALYST_QUALIFICATION_AUTHORITY` is a guarded setting (9kg.30: read from the
  environment, accepted only as `explicit_permission` or unset) and is unset until POL-05 is recorded; while unset
  everyone is refused, superusers included (TEST-P3-04). Once set, the actor must be an authenticated, active,
  non-superuser human holding `assessments.record_qualification_decision` by explicit grant (no group carries it;
  the owner-run `grant_staff_role` command grants it);
- **what the decision-maker saw is still true**: the decision digest shown on the screen (the current snapshot
  manifest, the clarification question set, and the run relied on) equals the one recomputed now (TEST-P3-51);
- **the assessment is valid**: the latest succeeded run is on the current snapshot (a re-fetch or a newly confirmed
  answer makes it stale: reassess first), no run is in flight and no evidence item is pending; or, when model
  advice is unavailable for this snapshot or suspended, a **recorded human-only assessment** (D-35) with a reason;
- **the stage** is compare-and-set from `awaiting_decision`, from `on_hold` (9kg.50: the staff path back from a hold
  to an admit or a decline, never a second hold) or from `assessing` for a human-only assessment after a failed run;
  no identity-affecting staff item is open; `admit` is refused while automation is paused;
- **every rubric criterion** has a human rationale with capability and strength of evidence recorded separately;
- **no v2 decline for an existing member** (030 Q8, 9kg.52): a decline is refused (`decline_refused_member_on_file`)
  while the address has a live first-generation agreement-on-file record (applications.members); hold, or withdraw
  through the withdrawal path, instead;
- **the internal cohort's trial boundary** (9kg.85; council record 033 Q5 and Q6, D-52) in a live environment: no
  decline at all (`decline_refused_in_the_internal_cohort`; hold, or withdraw through the withdrawal path), and every
  criterion recorded unrated, capability `unknown` with evidence strength `none`
  (`cohort_criteria_must_be_unrated`), so taking part is never an appraisal of a colleague. `COHORT_BOUNDARY` is
  lifted only by a reviewed release before wider enrollment.

bgl.12 (`record_routine_admit`): under `CATALYST_ROUTINE_ADVANCE_ACTIVATION` (0 in code) the routine-advance policy
(`assessments.policy`, acted on by `assessments.routine`) may record an **admit** on this same path with the same
record and refusals, as `actor_ref` `policy:routine_advance:v<n>`; it never records a decline or a hold, and the
human screen is unchanged. At the default configuration no such decision exists.

Then: the `QualificationDecision` row, the stage move (`admitted`, `declined` or `on_hold`), an event, and the
follow-on: a held `issue_nda:<application>` for admit (P4 releases it); for decline a queued
`send_decline:<application>` (oc4.11, `assessments.decline`: the decline notice), unless the decision-maker chose to
withhold the notice, with a reason, which the decision records (`decision_inputs["decline_notice"]`) and which queues
nothing; nothing for hold. A database trigger refuses any move into a decided stage without a decision row inserted
in the same transaction (TEST-P3-52). No model output is read to choose anything here.

oc4.12 (019 decision 4; 018 section 20): the decision digest binds, and the decision records in `decision_inputs`,
the policy reference (the synthetic rubric's `none-approved` reference stated openly until a policy is bound), the
pack digest and rubric version, the snapshot digest with an evidence manifest (present, unavailable, refused,
size-limited, claims-only, pending) and every run with its status, error code and requests spent. A human-only
decision carries a structured reason (`HUMAN_ONLY_CODES`), derived from the state, never free text alone; under
the launch-wide suspension of model advice it is `advice_suspended` and cites the suspension record.
"""

import hashlib
import json
import re

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.backends import ModelBackend
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from applications import members
from applications.models import Application, ApplicationEvent, Stage
from applications.stages import StageConflict, transition
from correspondence.models import Question, StaffItem
from correspondence.processing import RESOLUTIONS
from correspondence.common import Refused as NoteRefused
from correspondence.staff_items import clean_note as _clean_note, resolve_item
from workflow.models import AutomationPause, PendingAction

from . import decline as declines, pack as packs, snapshot
from .models import AssessmentRun, EvidenceItem, QualificationDecision
from .services import Refused

STAGE_FOR = {"admit": Stage.ADMITTED, "decline": Stage.DECLINED, "hold": Stage.ON_HOLD}
FOLLOW_ON = {"admit": "issue_nda"}  # held; P4 releases it. A decline queues the notice instead (oc4.11, decline.py)
CAPABILITY = ("shown", "partly_shown", "not_shown", "unknown")
EVIDENCE_STRENGTH = ("strong", "moderate", "weak", "none")
# 9kg.85 (033 Q5, Q6): the internal cohort's trial boundary, enforced in a live environment while this is set.
COHORT_BOUNDARY = True
UNRATED = ("unknown", "none")  # (capability, evidence strength): nothing is rated
FAILED = ("refused", "invalid_output", "failed", "capped", "abandoned")
# oc4.12: why a human-only assessment applies, in order of precedence (the first that holds).
HUMAN_ONLY_CODES = ("advice_suspended", "run_capped", "run_failed", "run_cap_reached", "returned_without_reassessment")
EVIDENCE_STATES = ("present", "size_limited", "unavailable", "refused", "pending", "claims_only")
_REASON_CODE = re.compile(r"^[a-z][a-z_]{2,39}$")
NOTE_MAX = 500
# Staff items that concern who the applicant is: a decision waits until they are resolved (018 section 7).
IDENTITY_ITEMS = tuple(code for code, resolutions in RESOLUTIONS.items()
                       if "resolve_identity_exception" in resolutions.values())


def clean_note(text: str) -> str:
    try:
        return _clean_note(text)
    except NoteRefused as exc:
        raise Refused(str(exc)) from None


def can_decide(user) -> bool:
    """POL-05 recorded, and a staff human holding the permission **directly**: a group grant never counts, so the
    authority cannot spread by adding the permission to a group (3B.4 reviews)."""
    if settings.CATALYST_QUALIFICATION_AUTHORITY is None or user is None or not user.is_authenticated:
        return False
    if not user.is_active or user.is_superuser or not user.is_staff:
        return False
    return "assessments.record_qualification_decision" in ModelBackend().get_user_permissions(user)


def policy_ref(pack) -> str:
    """The selection policy the decision applies (019 section 6). While no policy is active: with model advice off
    (the internal cohort) the literal `CATALYST_NO_POLICY_LABEL` (030 Q8, D-M); otherwise the synthetic rubric stands
    in and the reference says so. The pack, its digest and the rubric version are recorded in their own columns
    whatever this says."""
    if settings.CATALYST_SELECTION_POLICY:
        return settings.CATALYST_SELECTION_POLICY
    if settings.CATALYST_ASSESSMENT_MODEL == "none":
        return settings.CATALYST_NO_POLICY_LABEL
    return f"none-approved:{pack.name}:rubric-{pack.rubric_version}"


def bound_pack() -> str:
    """The pack the active policy was approved with (oc4.10 item 1), or "" when no policy is active."""
    policy = settings.CATALYST_SELECTION_POLICY
    return (settings.CATALYST_SELECTION_POLICY_PACKS or {}).get(policy, "") if policy else ""


def evidence_manifest(application, manifest) -> list:
    """018 section 20: one state per claim, for the record and the digest: `present` (a capture), `size_limited` (a
    truncated capture), `unavailable`, `refused`, `pending`, or `claims_only` (no approved source: the claim went to the
    assessment as a statement only)."""
    from .models import EvidenceCapture

    by_claim = {entry["claim"]: entry for entry in manifest["items"]}
    truncated = set(EvidenceCapture.objects.filter(pk__in=[e["capture"] for e in by_claim.values() if e["capture"]],
                                                   truncated=True).values_list("pk", flat=True))
    version = application.versions.get(public_id=manifest["version"])
    claims = (version.submitted_fields or {}).get("claims") or {}
    refs = [f"work:{i}" for i in range(1, len(claims.get("work") or []) + 1)]
    refs += [f"credential:{i}" for i in range(1, len(claims.get("credentials") or []) + 1)]
    out = []
    for ref in sorted({*refs, *by_claim}):
        entry = by_claim.get(ref)
        if entry is None:
            state = "claims_only"
        elif entry["status"] == "fetched":
            state = "size_limited" if entry["capture"] in truncated else "present"
        else:
            state = entry["status"]
        out.append({"claim": ref, "state": state})
    return out


def runs_summary(application) -> list:
    return [{"run": str(r.public_id), "status": r.status, "error_code": r.error_code, "requests_used": r.requests_used}
            for r in AssessmentRun.objects.filter(application=application).order_by("id")]


def human_only_code(application, run, current: str, succeeded, in_flight: bool) -> str:
    """The one source of the human-only rule (D-35, oc4.12): the structured reason a human-only assessment applies
    now, or "" when none does. Never while a valid run exists for the current snapshot, a run is in flight or there
    is no snapshot. A capped snapshot is an exit only while CATALYST_CAPPED_EXIT is "human_only" (oc4.8)."""
    if succeeded is not None or in_flight or not current:
        return ""
    if settings.CATALYST_ASSESSMENT_MODEL == "none":
        return "advice_suspended"
    capped_exit = settings.CATALYST_CAPPED_EXIT == "human_only"
    on_current = run is not None and run.snapshot_sha256 == current
    if on_current and run.status == "capped":
        return "run_capped" if capped_exit else ""
    if on_current and run.status in FAILED:
        return "run_failed"
    if application.stage in (Stage.AWAITING_DECISION, Stage.ON_HOLD):
        return "returned_without_reassessment"  # handed back without a reassessment (the round cap, or none could be queued)
    if (application.stage == Stage.ASSESSING  # no run can be queued any more: the run cap is reached
            and AssessmentRun.objects.filter(application=application).count() >= settings.CATALYST_ASSESSMENT_RUNS_PER_APPLICATION):
        return "run_cap_reached" if capped_exit else ""
    return ""


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
    in_flight = AssessmentRun.objects.filter(application=application, status__in=("queued", "reserved")).exists()
    # Human-only (D-35): computed once, in `human_only_code`; allowed exactly when a code applies.
    code = human_only_code(application, run, current, succeeded, in_flight)
    human_only_allowed = code != ""
    evidence = evidence_manifest(application, manifest) if manifest is not None else []
    runs = runs_summary(application)
    policy = policy_ref(pack) if pack is not None else ""
    return {"pack": pack, "manifest": manifest, "snapshot": current, "run": succeeded, "latest_run": run,
            "stale_run": run is not None and succeeded is None and run.status == "succeeded",
            "questions": questions, "human_only_allowed": human_only_allowed,
            "policy_ref": policy, "pack_sha256": pack.sha256 if pack else "", "rubric_version": pack.rubric_version if pack else 0,
            "evidence_manifest": evidence, "runs": runs, "human_only_code": code,
            "suspension_ref": settings.CATALYST_MODEL_ADVICE_SUSPENSION_REF if code == "advice_suspended" else "",
            "digest": _sha({"snapshot": current, "questions": questions, "run": str(succeeded.public_id) if succeeded else "",
                            "policy": policy, "pack_sha256": pack.sha256 if pack else "", "evidence": evidence, "runs": runs})}


def _rationale(pack, rationale: dict) -> dict:
    ids = [c["id"] for c in pack.criteria]
    if not isinstance(rationale, dict) or sorted(rationale) != sorted(ids):
        raise Refused("rationale_needed_for_every_criterion")
    out = {}
    for criterion in ids:
        entry = rationale[criterion]
        if not isinstance(entry, dict):
            raise Refused("rationale_needs_capability_and_evidence_strength")
        if entry.get("capability") not in CAPABILITY or entry.get("evidence_strength") not in EVIDENCE_STRENGTH:
            raise Refused("rationale_needs_capability_and_evidence_strength")
        if entry["evidence_strength"] == "none" and entry["capability"] != "unknown":
            # 019 section 5: with no evidence, capability is unknown; absence of evidence is never lack of ability
            raise Refused("rationale_no_evidence_means_capability_unknown")
        raw = str(entry.get("note", ""))
        if len(raw.strip()) > NOTE_MAX:
            raise Refused("rationale_note_too_long")  # refused, not silently cut: the record is what was written
        note = clean_note(raw)
        if not note:
            raise Refused("rationale_needs_a_note")
        out[criterion] = {"capability": entry["capability"], "evidence_strength": entry["evidence_strength"], "note": note}
    return out


def cohort_boundary() -> bool:
    """9kg.85: whether the internal cohort's trial boundary applies here (set, and the environment is live)."""
    from config.guards import LIVE_ENVIRONMENTS

    return COHORT_BOUNDARY and settings.CATALYST_ENV in LIVE_ENVIRONMENTS


def record_decision(application_id: int, user, *, outcome: str, reason_code: str, reason_text: str = "",
                    expected_digest: str, rationale: dict, human_only_reason: str = "", decline_notice: str = declines.SEND,
                    withhold_reason: str = "") -> QualificationDecision:
    if settings.CATALYST_QUALIFICATION_AUTHORITY is None:
        raise Refused("no_decision_authority_configured")  # POL-05: everyone, superusers included
    if not can_decide(user):
        raise PermissionDenied("record_qualification_decision")
    if outcome not in STAGE_FOR:
        raise Refused("unknown_outcome")
    if outcome == "decline" and cohort_boundary():
        raise Refused("decline_refused_in_the_internal_cohort")  # 033 Q5: hold or withdraw a member instead
    if not _REASON_CODE.match(reason_code or ""):
        raise Refused("reason_code_invalid")
    if len((reason_text or "").strip()) > NOTE_MAX or len((human_only_reason or "").strip()) > 300:
        raise Refused("text_too_long")
    reason_text = clean_note(reason_text)
    human_only = bool(human_only_reason.strip())
    human_only_reason = clean_note(human_only_reason) if human_only else ""
    notice = _notice_choice(outcome, decline_notice, withhold_reason)
    actor = f"user:{user.pk}"
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        state = decision_state(application)
        if state["pack"] is None or state["manifest"] is None:
            raise Refused("no_snapshot")
        if expected_digest != state["digest"]:
            raise Refused("changed_since_shown")  # a re-fetch, a confirmed answer, a question set change, a new run, a policy change
        if settings.CATALYST_SELECTION_POLICY and state["pack"].name != bound_pack():
            raise Refused("policy_not_bound_to_pack")  # oc4.10 item 1: a policy labels only decisions under its own pack
        if AssessmentRun.objects.filter(application=application, status__in=("queued", "reserved")).exists():
            raise Refused("assessment_in_flight")
        version = application.versions.get(public_id=state["manifest"]["version"])
        if EvidenceItem.objects.filter(application=application, adopted_version=version, status="pending").exists():
            raise Refused("evidence_pending")
        if human_only:
            if not state["human_only_allowed"]:
                raise Refused("human_only_assessment_not_allowed")  # never a shortcut past a working assessment
            run, from_stages = None, (Stage.AWAITING_DECISION, Stage.ASSESSING, Stage.ON_HOLD)
        else:
            run = state["run"]
            if run is None:
                raise Refused("no_valid_assessment")  # P3-D-10: rerun, or reassess after new evidence or answers
            from_stages = (Stage.AWAITING_DECISION, Stage.ON_HOLD)
        if application.stage not in from_stages:
            raise Refused("stage_not_decidable")
        if application.stage == Stage.ON_HOLD and outcome == "hold":
            raise Refused("already_on_hold")  # 9kg.50: the way off a hold is a decision, not another hold
        if StaffItem.objects.filter(application=application, status="open", reason_code__in=IDENTITY_ITEMS).exists():
            raise Refused("identity_item_open")
        if Question.objects.filter(application=application, approval_state=Question.Approval.APPROVED,
                                   status__in=(Question.Status.OPEN, Question.Status.REPLY_PENDING)).exists():
            raise Refused("open_question_pending")  # sent and unanswered: withdraw it first (its reminders stop too)
        if outcome == "decline" and members.on_file(application) is not None:
            raise Refused("decline_refused_member_on_file")  # 030 Q8: hold or withdraw an existing member instead
        if outcome == "admit" and AutomationPause.objects.filter(subject_type="application",
                                                                 subject_id=application.public_ref).exists():
            raise Refused("admit_refused_while_paused")
        checked = _rationale(state["pack"], rationale)
        if cohort_boundary() and any((e["capability"], e["evidence_strength"]) != UNRATED for e in checked.values()):
            raise Refused("cohort_criteria_must_be_unrated")  # 033 Q6: never an appraisal of a colleague
        code = state["human_only_code"] if human_only else ""
        inputs = {"policy": state["policy_ref"], "pack": state["pack"].name, "pack_sha256": state["pack_sha256"],
                  "rubric_version": state["rubric_version"], "snapshot": state["snapshot"],
                  "evidence": state["evidence_manifest"], "runs": state["runs"], "questions": state["questions"],
                  "human_only_code": code, "suspension_ref": state["suspension_ref"] if human_only else ""}
        if notice is not None:
            inputs["decline_notice"] = notice  # oc4.11: the decision-maker's choice, recorded with the decision
        try:
            with transaction.atomic():
                decision = QualificationDecision.objects.create(
                    application=application, adopted_version=version, run=run, outcome=outcome,
                    basis=QualificationDecision.Basis.HUMAN_ONLY if human_only else QualificationDecision.Basis.MODEL_ASSISTED,
                    human_only_reason=human_only_reason, human_only_code=code, reason_code=reason_code, reason_text=reason_text,
                    rationale=checked, snapshot_sha256=state["snapshot"], decision_digest=state["digest"],
                    policy_ref=state["policy_ref"], prompt_pack=state["pack"].name, prompt_pack_sha256=state["pack_sha256"],
                    rubric_version=state["rubric_version"], decision_inputs=inputs, actor_ref=actor)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "")
            if constraint == "decision_one_final_per_application":
                raise Refused("already_decided") from None  # one admit or decline per application (TEST-P3-45)
            raise Refused("decision_invalid") from None
        _follow_on(application, decision, from_stages, code, actor, ApplicationEvent.ActorType.STAFF)
        if human_only:  # oc4.12: the suspended (or capped) item is answered by this decision; it must not page forever
            for item in StaffItem.objects.filter(application=application, status=StaffItem.Status.OPEN,
                                                 reason_code__in=("assessment_suspended", "assessment_capped")):
                resolve_item(item, code="human_only_decision", actor_ref=actor, effects={"decision": str(decision.public_id)},
                             actor_type=ApplicationEvent.ActorType.STAFF)
        if notice is not None and notice["choice"] == declines.SEND:
            declines.enqueue(application, decision)  # exactly one notice per decline (the key is per application)
        elif notice is not None:
            ApplicationEvent.objects.create(application=application, kind="decline_notice_withheld",
                                            actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor,
                                            data={"decision": str(decision.public_id), "reason": notice["reason"]})
    return decision


def _follow_on(application, decision, from_stages, code: str, actor: str, actor_type) -> None:
    """The stage move, the withdrawal of unsent proposed questions and the held follow-on action, shared by the human
    decision and the routine policy's admit (bgl.12). Inside the decision's transaction."""
    outcome = decision.outcome
    try:
        transition(application.pk, from_stages, STAGE_FOR[outcome], event_kind=f"qualification_{outcome}",
                   data={"decision": str(decision.public_id), "basis": decision.basis, "policy": decision.policy_ref,
                         "human_only_code": code},
                   actor_type=actor_type, actor_ref=actor)
    except StageConflict:
        raise Refused("stage_not_decidable") from None
    # Unsent proposed questions end with the decision: nothing is sent to a decided applicant (3B.4 review).
    unsent = Question.objects.filter(application=application, approval_state=Question.Approval.PROPOSED).exclude(
        status=Question.Status.WITHDRAWN)
    withdrawn = [str(q) for q in unsent.values_list("public_id", flat=True)]
    unsent.update(status=Question.Status.WITHDRAWN, withdrawn_by=actor, withdrawn_reason="decided",
                  withdrawn_at=Now(), updated_at=Now())
    if withdrawn:
        ApplicationEvent.objects.create(application=application, kind="questions_withdrawn_by_decision",
                                        actor_type=actor_type, actor_ref=actor,
                                        data={"decision": str(decision.public_id), "questions": withdrawn})
    kind = FOLLOW_ON.get(outcome)
    if kind:
        PendingAction.objects.create(kind=kind, subject_type="application", subject_id=application.public_ref,
                                     input_ref=str(decision.public_id), idempotency_key=f"{kind}:{application.public_ref}",
                                     status=PendingAction.Status.HELD)


ROUTINE_REASON = "routine_advance"  # the reason code of every automatic admit; the actor names the policy version


def record_routine_admit(application, run, *, rationale: dict, verdict: dict, actor: str) -> QualificationDecision:
    """bgl.12 (034 rows 15 and 18): the routine-advance policy's admit, on the existing admit path and with the same
    record, inside the caller's transaction with the application locked. The decision stands on the valid succeeded run
    for the current snapshot (basis `model_assisted`), carries the policy's per-criterion rationale (validated like a
    human's) and its verdict in `decision_inputs`, and ends in the same held `issue_nda`. Everything the human path
    refuses is refused here too (a stale run, pending evidence, an open identity item, an open question, a pause, the
    cohort boundary), and the authority setting is not consulted: this is not a person deciding, and the policy runs
    only under its own activation. Never a decline, never a hold."""
    state = decision_state(application)
    if state["pack"] is None or state["manifest"] is None:
        raise Refused("no_snapshot")
    if settings.CATALYST_SELECTION_POLICY and state["pack"].name != bound_pack():
        raise Refused("policy_not_bound_to_pack")
    if state["run"] is None or state["run"].pk != run.pk:
        raise Refused("no_valid_assessment")  # the run is stale or superseded: nothing automatic stands on it
    if AssessmentRun.objects.filter(application=application, status__in=("queued", "reserved")).exists():
        raise Refused("assessment_in_flight")
    version = application.versions.get(public_id=state["manifest"]["version"])
    if EvidenceItem.objects.filter(application=application, adopted_version=version, status="pending").exists():
        raise Refused("evidence_pending")
    if application.stage != Stage.AWAITING_DECISION:
        raise Refused("stage_not_decidable")
    if StaffItem.objects.filter(application=application, status="open", reason_code__in=IDENTITY_ITEMS).exists():
        raise Refused("identity_item_open")
    if Question.objects.filter(application=application, approval_state=Question.Approval.APPROVED,
                               status__in=(Question.Status.OPEN, Question.Status.REPLY_PENDING)).exists():
        raise Refused("open_question_pending")
    if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
        raise Refused("admit_refused_while_paused")
    if cohort_boundary():
        raise Refused("cohort_boundary")  # 033 Q6: nothing automatic in the internal cohort
    checked = _rationale(state["pack"], rationale)
    inputs = {"policy": state["policy_ref"], "pack": state["pack"].name, "pack_sha256": state["pack_sha256"],
              "rubric_version": state["rubric_version"], "snapshot": state["snapshot"],
              "evidence": state["evidence_manifest"], "runs": state["runs"], "questions": state["questions"],
              "human_only_code": "", "suspension_ref": "", "routine_policy": verdict}
    try:
        with transaction.atomic():
            decision = QualificationDecision.objects.create(
                application=application, adopted_version=version, run=run, outcome="admit",
                basis=QualificationDecision.Basis.MODEL_ASSISTED, reason_code=ROUTINE_REASON,
                reason_text="", rationale=checked, snapshot_sha256=state["snapshot"], decision_digest=state["digest"],
                policy_ref=state["policy_ref"], prompt_pack=state["pack"].name, prompt_pack_sha256=state["pack_sha256"],
                rubric_version=state["rubric_version"], decision_inputs=inputs, actor_ref=actor)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "")
        raise Refused("already_decided" if constraint == "decision_one_final_per_application" else "decision_invalid") from None
    _follow_on(application, decision, (Stage.AWAITING_DECISION,), "", actor, ApplicationEvent.ActorType.SYSTEM)
    return decision


def _notice_choice(outcome: str, choice: str, reason: str) -> dict | None:
    """oc4.11: the decline notice is sent unless the decision-maker withholds it, with a reason of at least
    WITHHOLD_REASON_MIN characters (when withholding is appropriate is the owner's rule; the code records the choice).
    Only a decline makes the choice; any other outcome must leave it at the default."""
    if choice not in declines.CHOICES:
        raise Refused("decline_notice_choice_invalid")
    if outcome != "decline":
        if choice != declines.SEND:
            raise Refused("decline_notice_choice_only_for_decline")
        return None  # an admit or a hold sends no notice; a reason typed for a withheld notice is not recorded
    if choice == declines.SEND:
        if (reason or "").strip():
            raise Refused("withhold_reason_only_when_withholding")
        return {"choice": declines.SEND}
    if len((reason or "").strip()) > declines.WITHHOLD_REASON_MAX:
        raise Refused("text_too_long")
    reason = clean_note(reason)
    if len(reason) < declines.WITHHOLD_REASON_MIN:
        raise Refused("withhold_reason_needed")
    return {"choice": declines.WITHHOLD, "reason": reason}
