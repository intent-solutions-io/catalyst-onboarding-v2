"""The automated company countersignature (bead bgl.9; 034 row 30; first-generation decision 12, counsel-approved, carried
to v2 by the owner's YES of 2026-10-31). Off by default: `CATALYST_AGREEMENT_COUNTERSIGN` is "manual" and the owner
countersigns by hand at the provider, as before (029 section 4.5, the manual handoff).

Under "automatic":

- `CountersignSweep` (`countersign_sweep`, every `CATALYST_AGREEMENT_COUNTERSIGN_SWEEP_SECONDS`, 600 by default, like the
  first generation's timer) finds, from the database only, the issued v2 agreements that carry a company recipient and
  still wait for signatures, and queues one `countersign_agreement` per agreement (coalesced). A fresh read that shows the
  applicant signed queues one at once as well (`after_read`, called by `completion.apply_read`).
- `CountersignAgreement` (`countersign_agreement`, automated, so a paused case is never countersigned) reads the envelope
  afresh, signs nothing unless the read shows our envelope (v2's `ag_` key, our template, exactly our recipients),
  PENDING, the applicant signed and the company recipient not; then takes the single-writer claim (`CountersignClaim`,
  unique on the envelope, `ag_` keys only), journals the effect, signs as the company recipient through the provider
  (`provider.countersign`) and verifies by a second fresh read. The completed envelope is then verified by the ordinary
  read path (a read queued at once), never by this module.
- A failure retries every `CATALYST_AGREEMENT_COUNTERSIGN_RETRY_SECONDS`; once `CATALYST_AGREEMENT_COUNTERSIGN_HANDOFF_SECONDS`
  (30 minutes) have passed since the first failure, or the attempts are spent, the claim is handed off: one staff item
  (`agreement_countersign_needs_owner`) and the owner countersigns by hand, the manual handoff that is today's only path.
  The first generation emailed the owner a link at that point; v2 has no owner mail, so the staff queue carries it.
- A refusal (not our envelope, recipients changed, the company recipient expired or not signable, unexpected company
  fields) signs nothing and opens one staff item per agreement and reason (`agreement_countersign_refused`).

Single writer across services: the claim refuses any envelope whose key is not a v2 key, and both the read check and
`provider.countersign` compare the provider's `externalId` with the instance's key, so v2 never touches an envelope it
did not create. The first-generation bridge takes its own claim in the first generation's database and matches only its
own templates and `onb_` keys; that it cannot match a v2 envelope is the Documenso canary's negative control (029
section 6, `dy7.2`), not something this module can prove.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Coalesce, Now

from applications.models import Application, Stage
from correspondence.models import StaffItem
from correspondence.staff_items import event, open_item, resolve_item
from workflow import journal, ledger
from workflow.models import PendingAction

from . import provider
from .models import AgreementInstance, CountersignClaim

COUNTERSIGN = "countersign_agreement"
SWEEP = "countersign_sweep"
SWEEP_SUBJECT = ("system", uuid.UUID("00000000-0000-0000-0000-00000000c051"))
HOLDER = "catalyst_v2"  # the writer recorded on the claim
JOURNAL_KIND = "agreement_countersign"
HANDED_OFF = "agreement_countersign_needs_owner"  # the owner countersigns by hand (the manual handoff)
REFUSED = "agreement_countersign_refused"
WAITING = ("not_started", "partially_signed")
Status = PendingAction.Status
State = CountersignClaim.State


def automatic() -> bool:
    return settings.CATALYST_AGREEMENT_COUNTERSIGN == "automatic"


def company(instance):
    """The company recipient (P4-D-3: a second recipient at order 2 once named), or None."""
    return instance.recipients.filter(who="staff").order_by("signing_order").first()


def _key(instance) -> str:
    return f"countersign:{instance.public_id}"


def _settled(instance) -> bool:
    """Nothing more for automation: signed or handed off, or a refusal or hand-off still open for staff."""
    if CountersignClaim.objects.filter(instance=instance, state__in=(State.SIGNED, State.HANDED_OFF)).exists():
        return True
    return StaffItem.objects.filter(reason_code__in=(REFUSED, HANDED_OFF), dedupe_key__startswith=_key(instance),
                                    status=StaffItem.Status.OPEN).exists()


def eligible(instance) -> str:
    """The database half: an empty string, or why this agreement is not one to countersign now."""
    if not instance.external_key.startswith("ag_"):
        return "not_a_v2_envelope"
    if (instance.issue_status != "issued" or not instance.envelope_id or instance.replaced_at
            or instance.signing_status not in WAITING or instance.cancel_requested_at):
        return "not_waiting_for_signatures"
    if company(instance) is None:
        return "no_company_recipient"
    from .completion import stopped

    application = instance.application
    if application.stage != Stage.AGREEMENTS or stopped(application):
        return "not_in_agreements"
    return ""


def enqueue(instance, due_in: timedelta | None = None) -> PendingAction | None:
    """One queued or running countersign per agreement at most. Inside the caller's transaction."""
    if not automatic() or eligible(instance) or _settled(instance):
        return None
    ref = str(instance.public_id)
    live = PendingAction.objects.filter(kind=COUNTERSIGN, input_ref=ref, status__in=(Status.QUEUED, Status.RUNNING)).first()
    if live is not None:
        return live
    n = PendingAction.objects.filter(kind=COUNTERSIGN, input_ref=ref).count() + 1
    return PendingAction.objects.create(
        kind=COUNTERSIGN, subject_type="application", subject_id=instance.application.public_ref, input_ref=ref,
        idempotency_key=f"{COUNTERSIGN}:{ref}:{n}", due_at=Now() + (due_in or timedelta(0)),
        max_attempts=settings.CATALYST_AGREEMENT_COUNTERSIGN_ATTEMPTS)


def after_read(instance, env: provider.Envelope) -> None:
    """Called by the read path (completion.apply_read) inside its result transaction: a read that shows the applicant
    signed and the company recipient not queues the countersignature now, rather than at the next sweep."""
    if not automatic() or env.status != "PENDING":
        return
    states = _signing_states(instance, env)
    if states == ("SIGNED", "NOT_SIGNED"):
        enqueue(AgreementInstance.objects.select_related("application").get(pk=instance.pk))


def _signing_states(instance, env) -> tuple:
    """(the applicant's, the company recipient's) signing status in a provider view, matched by address and role."""
    ours = {(r.who, r.email.lower(), r.role) for r in instance.recipients.all()}
    found = {}
    for r in env.recipients:
        for who, email, role in ours:
            if r.email.lower() == email and r.role == role:
                found[who] = r
    applicant, staff = found.get("applicant"), found.get("staff")
    return (applicant.signing_status if applicant else "", staff.signing_status if staff else "")


def check(instance, env: provider.Envelope) -> str:
    """The provider half, on a fresh read: an empty string when the company may countersign now; otherwise "waiting",
    "already_signed", "not_pending" (nothing for staff) or a refusal code."""
    from .completion import facts, read_identity

    if not read_identity(instance, env) or not env.external_id.startswith("ag_"):
        return "not_a_v2_envelope"  # never ours to touch
    if env.status == "COMPLETED":
        return "already_signed"
    if env.status != "PENDING":
        return "not_pending"  # declined, cancelled or still a draft: the read path handles it
    if not facts(instance, env.status, env.recipients, identity=True)["recipients_match"]:
        return "recipients_changed"
    applicant, staff = _signing_states(instance, env)
    if staff == "SIGNED":
        return "already_signed"
    if any(r.expired for r in env.recipients):
        return "recipient_expired"
    if applicant != "SIGNED":
        return "waiting"
    return "" if staff == "NOT_SIGNED" else "company_recipient_not_signable"


def take_claim(instance, action_id: int) -> str:
    """The single-writer claim, inside the caller's transaction with the application and the instance locked. Returns
    "taken", or why not: another writer or action holds it, it is settled, or the envelope is not a v2 envelope (the
    database refuses that row as well)."""
    if not instance.external_key.startswith("ag_"):
        return "not_a_v2_envelope"
    row = CountersignClaim.objects.select_for_update(of=("self",)).filter(envelope_id=instance.envelope_id).first()
    if row is None:
        try:
            with transaction.atomic():
                CountersignClaim.objects.create(instance=instance, envelope_id=instance.envelope_id,
                                                external_key=instance.external_key, holder=HOLDER, action_id=action_id,
                                                state=State.SIGNING, attempts=1)
        except IntegrityError:
            return "already_claimed"  # a concurrent writer inserted it first
        return "taken"
    if row.instance_id != instance.pk or row.holder != HOLDER or row.external_key != instance.external_key:
        return "already_claimed"
    if row.state in (State.SIGNED, State.HANDED_OFF):
        return f"claim_{row.state}"
    if row.action_id != action_id and PendingAction.objects.filter(
            pk=row.action_id, status=Status.RUNNING, lease_expires_at__gt=Now()).exists():
        return "already_claimed"  # another action is working under it right now
    CountersignClaim.objects.filter(pk=row.pk).update(action_id=action_id, state=State.SIGNING, attempts=F("attempts") + 1,
                                                      updated_at=Now())
    return "taken"


def _refuse(claim, instance, code: str) -> None:
    """One staff item and one event per agreement and reason; the claim, if any, records the code."""
    key = f"{_key(instance)}:{code}"
    if not StaffItem.objects.filter(reason_code=REFUSED, dedupe_key=key, status=StaffItem.Status.OPEN).exists():
        open_item(REFUSED, key, application=instance.application, pending_action_id=claim.id)
        event(instance.application, "agreement_countersign_refused", {"instance": str(instance.public_id), "reason": code},
              actor_ref=f"pending_action:{claim.id}")
    CountersignClaim.objects.filter(instance=instance, state__in=(State.SIGNING, State.FAILED)).update(
        state=State.FAILED, last_code=code[:64], updated_at=Now())


def _hand_off(claim_id, instance, code: str) -> None:
    CountersignClaim.objects.filter(instance=instance).exclude(state=State.SIGNED).update(
        state=State.HANDED_OFF, last_code=code[:64], updated_at=Now(), finished_at=Now())
    key = _key(instance)
    if not StaffItem.objects.filter(reason_code=HANDED_OFF, dedupe_key=key, status=StaffItem.Status.OPEN).exists():
        open_item(HANDED_OFF, key, application=instance.application, pending_action_id=claim_id)
        event(instance.application, "agreement_countersign_handed_off", {"instance": str(instance.public_id),
                                                                         "reason": code}, actor_ref=f"pending_action:{claim_id}")


class CountersignAgreement:
    kind = COUNTERSIGN
    automated = True  # a paused case is never countersigned: the claim waits
    redeliverable = False  # a write whose outcome may be unknown: the next attempt reads first

    def lock_subject(self, claim) -> None:
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            AgreementInstance.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref,
                                                                             application=application).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            instance = AgreementInstance.objects.select_related("application").filter(public_id=claim.input_ref).first()
            if instance is not None:
                _hand_off(claim.id, instance, "attempts_exhausted")

    def _instance(self, claim):
        instance = (AgreementInstance.objects.select_related("application", "template_version")
                    .filter(public_id=claim.input_ref).first())
        if instance is None or str(instance.application.public_ref) != str(claim.subject_id):
            return None
        return instance

    def _failed(self, claim, instance, code: str) -> None:
        """Bounded retries; then the hand-off, once the window since the first failure has passed or no attempt is
        left."""
        window = timedelta(seconds=settings.CATALYST_AGREEMENT_COUNTERSIGN_HANDOFF_SECONDS)
        CountersignClaim.objects.filter(instance=instance, state=State.SIGNING).update(
            state=State.FAILED, last_code=code[:64], first_failure_at=Coalesce("first_failure_at", Now()), updated_at=Now())
        row = CountersignClaim.objects.filter(instance=instance).first()
        overdue = row is not None and CountersignClaim.objects.filter(pk=row.pk, first_failure_at__lte=Now() - window).exists()
        if claim.final or overdue:
            ledger.finish(claim, self, status=Status.FAILED, error=code, write=lambda: _hand_off(claim.id, instance, code))
            return
        ledger.finish(claim, self, status=Status.QUEUED, error=code,
                      due_in=timedelta(seconds=settings.CATALYST_AGREEMENT_COUNTERSIGN_RETRY_SECONDS))

    def run(self, claim) -> None:
        instance = self._instance(claim)
        reason = "countersign_manual" if not automatic() else ("instance_not_found" if instance is None else "")
        reason = reason or eligible(instance) or ("settled" if _settled(instance) else "")
        if reason:
            ledger.finish(claim, self, status=Status.DONE, error=reason)
            return
        try:
            env = provider.read(instance.envelope_id)  # the first fresh read, outside any transaction
        except provider.ProviderError as exc:
            self._failed(claim, instance, f"read_{exc.code}")
            return
        problem = check(instance, env)
        if problem in ("waiting", "not_pending"):
            ledger.finish(claim, self, status=Status.DONE, error=problem)
            return
        if problem == "already_signed":  # by hand, or by an earlier attempt whose answer was lost
            ledger.finish(claim, self, status=Status.DONE, error=problem, write=lambda: self._signed(claim, instance, False))
            return
        if problem:
            ledger.finish(claim, self, status=Status.DONE, error=problem, write=lambda: _refuse(claim, instance, problem))
            return
        try:
            with transaction.atomic():
                self.lock_subject(claim)
                ledger.fence(claim)
                taken = take_claim(instance, claim.id)
        except ledger.LeaseLost:
            return
        if taken != "taken":
            ledger.finish(claim, self, status=Status.DONE, error=taken)
            return
        # The effect is journaled before it is attempted (workflow.effects): a restore to before this point learns
        # that a countersignature may exist; the restored run reads first and finds it.
        journal.append(JOURNAL_KIND, _key(instance), {"phase": "begun"})
        recipient = company(instance)
        try:
            provider.countersign(instance.envelope_id, instance.external_key, recipient.email, recipient.role,
                                 settings.CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE)
        except provider.CountersignRefused as exc:
            code = exc.code
            ledger.finish(claim, self, status=Status.DONE, error=code, write=lambda: _refuse(claim, instance, code))
            return
        except provider.ProviderError as exc:
            self._failed(claim, instance, exc.code)
            return
        try:
            after = provider.read(instance.envelope_id)  # verified by a fresh read, never by the call's answer
        except provider.ProviderError as exc:
            self._failed(claim, instance, f"verify_{exc.code}")
            return
        if check(instance, after) != "already_signed":
            self._failed(claim, instance, "not_signed_after_countersign")
            return
        ledger.finish(claim, self, status=Status.DONE, write=lambda: self._signed(claim, instance, True))

    def _signed(self, claim, instance, ours: bool) -> None:
        from .completion import enqueue_read

        CountersignClaim.objects.filter(instance=instance).exclude(state=State.SIGNED).update(
            state=State.SIGNED, last_code="" if ours else "signed_elsewhere", updated_at=Now(), finished_at=Now())
        if ours:
            journal.record(JOURNAL_KIND, _key(instance), {"phase": "done", "outcome": "signed"})
            event(instance.application, "agreement_countersigned", {"instance": str(instance.public_id), "by": HOLDER},
                  actor_ref=f"pending_action:{claim.id}")
        for item in StaffItem.objects.filter(reason_code__in=(REFUSED, HANDED_OFF), dedupe_key__startswith=_key(instance),
                                             status=StaffItem.Status.OPEN):
            resolve_item(item, code="countersigned", actor_ref=f"pending_action:{claim.id}",
                         actor_type="system")
        enqueue_read(AgreementInstance.objects.get(pk=instance.pk))  # completion is verified by the read path


# --- the sweep ---------------------------------------------------------------------------------------------------

def schedule_sweep(n: int | None = None, delay: float = 0.0) -> bool:
    """Queue the next sweep unless one is queued or running; True when it queued one. Idempotent."""
    active = PendingAction.objects.filter(kind=SWEEP, status__in=(Status.QUEUED, Status.RUNNING))
    if n is None and active.exists():
        return False
    n = n if n is not None else PendingAction.objects.filter(kind=SWEEP).count() + 1
    try:
        with transaction.atomic():
            PendingAction.objects.create(kind=SWEEP, subject_type=SWEEP_SUBJECT[0], subject_id=SWEEP_SUBJECT[1],
                                         input_ref="", idempotency_key=f"{SWEEP}:{n}", due_at=Now() + timedelta(seconds=delay))
    except IntegrityError:
        return False
    return True


def candidates():
    return (AgreementInstance.objects.select_related("application", "template_version")
            .filter(issue_status="issued", signing_status__in=WAITING, replaced_at__isnull=True,
                    cancel_requested_at__isnull=True, external_key__startswith="ag_", recipients__who="staff",
                    application__stage=Stage.AGREEMENTS).exclude(envelope_id="").distinct().order_by("id"))


class CountersignSweep:
    kind = SWEEP
    automated = True
    redeliverable = True  # database only: it queues countersign actions, it signs nothing

    def lock_subject(self, claim) -> None:
        pass

    def _n(self, claim) -> int:
        key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""
        tail = key.rsplit(":", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    def record(self, claim, kind, data) -> None:
        if automatic() and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            schedule_sweep(self._n(claim) + 1, settings.CATALYST_AGREEMENT_COUNTERSIGN_SWEEP_SECONDS)

    def run(self, claim) -> None:
        if not automatic():  # manual mode: the chain ends here
            ledger.finish(claim, self, status=Status.DONE, error="countersign_manual")
            return
        for instance in candidates():
            with transaction.atomic():
                Application.objects.select_for_update(of=("self",)).filter(pk=instance.application_id).first()
                enqueue(instance)
        n = self._n(claim)
        ledger.finish(claim, self, status=Status.DONE,
                      write=lambda: schedule_sweep(n + 1, settings.CATALYST_AGREEMENT_COUNTERSIGN_SWEEP_SECONDS))
