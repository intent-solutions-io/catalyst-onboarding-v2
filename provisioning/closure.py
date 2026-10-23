"""P5 5B.3: withdrawal, closure and access revocation (023 sections 6, 11.5, 11.6 and 11.11; P5-D-8 to P5-D-11;
POL-12 for synthetic work). Synthetic only.

- `close_locked`: the one POL-12 stage move to `withdrawn` or `closed`, inside the caller's transaction with the
  application locked. It stops unfinished agreements (P4 `stop_locked`), records the stop intent on every live
  provisioning request (a create in flight becomes `stopping`, everything else `stopped`), cancels queued creates,
  invitations and activations, cancels live setups, and records the revocation obligations wherever a mailbox may
  exist. It never deletes mailbox data, never suspends a whole hosting user or domain, and never reopens anything.
- `close_application`: staff, with `close_application` and a reason: a closure, or a withdrawal the applicant asked
  for through staff (the staff-mediated path).
- `request_withdrawal_link` and `confirm_withdrawal`: the applicant's explicit, verified withdrawal (P5-D-8). Staff
  send a one-time link to the verified address on the applicant's request; GET shows, POST commits. An emailed
  "withdraw" is only ever a review item (P2 routes replies to staff).
- `RevokeAccess` (`provision_revoke`, protective): rotates the password to an unknown value (applied, not verifiable),
  removes forwarders the mailbox owns (verified by listing again), flags forwarders and the catch-all that name the
  address for staff, and leaves sessions and app credentials `unsupported` until a documented mechanism exists.
  Rotation never runs while a password set is pending, and repeats once after a settle delay (023 11.5).
- `accept_revocation_exception`: the owner accepts, with a reason, an obligation that cannot be completed.
"""

import hashlib
import logging
import secrets
from datetime import timedelta
from email.utils import make_msgid
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models.functions import Now

from applications.links import WITHDRAW_PATH
from applications.models import TERMINAL_STAGES, Application, ApplicationEvent, Stage
from applications.stages import transition
from correspondence.messages import verified_address
from workflow import journal, ledger
from workflow.models import PendingAction

from . import adapter, core, services
from .handlers import _Action
from .models import LIVE_REQUEST, AccessRevocation, CredentialSetup, ProvisioningRequest, WithdrawalConfirmation

logger = logging.getLogger(__name__)
Status = PendingAction.Status

REVOKE = "provision_revoke"
WITHDRAW_SEND = "provision_withdraw_send"
ITEM_REVOCATION = "provisioning_revocation_needs_staff"
ITEM_WITHDRAWAL = "provisioning_withdrawal_link_failed"
OUTCOMES = ("withdrawn", "closed")
MAILBOX_KINDS = ("password_rotation", "owned_forwarders", "sessions", "app_credentials")
DOMAIN_KINDS = ("inbound_forwarders", "catch_all")
SUBJECT = "Confirm that you want to withdraw"
BODY = ("Hello {name},\n\nYou asked to withdraw your application. To confirm, open this link (it works once and "
        "expires):\n\n{link}\n\nIf you did not ask for this, ignore this message; nothing changes.\n")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- the stage move -----------------------------------------------------------------------------------------------

def close_locked(application, outcome: str, reason: str, actor_ref: str, actor_type) -> None:
    from agreements import services as agreement_services

    if outcome not in OUTCOMES:
        raise services.Refused("unknown_outcome")
    if application.stage in TERMINAL_STAGES:
        raise services.Refused("already_closed")  # P5-D-10: nothing is reopened or closed twice
    if application.stage == Stage.AGREEMENTS:
        try:
            agreement_services.stop_locked(application, outcome, actor_ref, actor_type=actor_type)
        except agreement_services.Refused as exc:
            if str(exc) != "stopped_for_good":
                raise services.Refused(str(exc)) from None
    for request in ProvisioningRequest.objects.select_for_update(of=("self",)).filter(application=application):
        fields = {"updated_at": Now()}
        if request.stop_requested_at is None:
            fields["stop_requested_at"] = Now()
        if request.status in (*LIVE_REQUEST, "active"):
            fields["status"] = "stopping" if request.status in ("create_pending", "create_uncertain") else "stopped"
        ProvisioningRequest.objects.filter(pk=request.pk).update(**fields)
        PendingAction.objects.filter(input_ref=str(request.public_id), status__in=(Status.QUEUED, Status.HELD),
                                     kind__in=(core.CREATE, "provision_invite", "provision_activate")).update(
            status=Status.CANCELLED, completed_at=Now(), updated_at=Now(), last_error="application_closed")
        CredentialSetup.objects.filter(request=request, state__in=("invitation_pending", "invited", "presented")).update(
            state="cancelled", updated_at=Now())
        for code in (core.ITEM_CHECKLIST, core.ITEM_FAILED, core.ITEM_BLOCKED, "provisioning_setup_needs_staff",
                     "provisioning_activation_blocked"):
            services._resolve(request, code, "application_closed", actor_ref)
        request.refresh_from_db()
        if _may_hold_ours(request) or request.status in ("stopped", "stopping", "recovered_after_stop"):
            ensure_revocations(request, actor_ref)
    PendingAction.objects.filter(kind=core.HANDOFF, subject_id=application.public_ref, status=Status.HELD).update(
        status=Status.CANCELLED, completed_at=Now(), updated_at=Now(), last_error="application_closed")
    WithdrawalConfirmation.objects.filter(application=application, state__in=("pending", "sent", "uncertain")).update(
        state="superseded", updated_at=Now())
    to = Stage.WITHDRAWN if outcome == "withdrawn" else Stage.CLOSED
    transition(application.pk, (application.stage,), to, event_kind=f"application_{outcome}",
               data={"reason": reason}, actor_type=actor_type, actor_ref=actor_ref)
    # 9kg.33: a closure after a backup must survive the restore (the effect journal; replayed by provisioning.restore).
    journal.record("application_closed", f"application:{application.public_ref}", {"outcome": outcome})


def close_application(application_id: int, user, outcome: str, reason: str) -> None:
    services.require(user, "close_application")
    note = services._reason(reason)
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        close_locked(application, outcome, note, services.actor(user), ApplicationEvent.ActorType.STAFF)


# --- revocation obligations ---------------------------------------------------------------------------------------
#
# Two rules (reviews of PR #55): revocation acts only on a mailbox PROVEN to be ours (our create succeeded, the
# checklist creator recorded it, or staff confirmed a found one: 023 11.3, never adopt), and only once the request is
# SETTLED (no create whose outcome is still open). "Not applicable" is written only when a settled request never
# produced a mailbox of ours, so it is never written early and then frozen wrongly.

def proven_ours(request) -> bool:
    from .models import ProvisioningEvidence

    return (request.attempts.filter(step="create", outcome="succeeded").exists()
            or request.evidence.filter(kind=ProvisioningEvidence.Kind.CHECKLIST_CREATED).exists()
            or request.evidence.filter(kind=ProvisioningEvidence.Kind.STAFF_CONFIRMED, facts__decision="ours").exists())


def refused_as_foreign(request) -> bool:
    """Staff decided the found mailbox is not ours (the latest such decision)."""
    from .models import ProvisioningEvidence

    latest = request.evidence.filter(kind=ProvisioningEvidence.Kind.STAFF_CONFIRMED).order_by("-id").first()
    return latest is not None and (latest.facts or {}).get("decision") == "conflict"


def unproven_present(request) -> bool:
    """A mailbox was seen at the address but is not proven ours (found by evidence, a late watch match, a conflict
    after our own unknown create) and staff have not decided it."""
    from correspondence.models import StaffItem

    seen = (request.attempts.filter(step="create", outcome="found_by_evidence").exists()
            or request.attempts.filter(step="create", outcome="conflict",
                                       code__in=("present_but_not_provably_ours", "conflict_after_ours")).exists()
            or StaffItem.objects.filter(dedupe_key=f"provisioning:{request.public_id}", status=StaffItem.Status.OPEN,
                                        reason_code__in=(core.ITEM_LATE_MAILBOX, core.ITEM_CONFIRM_FOUND)).exists())
    return seen and not proven_ours(request) and not refused_as_foreign(request)


def _may_hold_ours(request) -> bool:
    return proven_ours(request) or services._mailbox_may_exist(request)


def _open_outcome(request) -> bool:
    return request.attempts.filter(step="create", outcome__in=("sending", "unknown")).exists() \
        or request.status in ("create_pending", "create_uncertain", "stopping")


def _reconciling(request) -> bool:
    return PendingAction.objects.filter(input_ref=str(request.public_id), kind__in=(core.CREATE, core.RECONCILE),
                                        status__in=(Status.QUEUED, Status.RUNNING)).exists()


def ensure_revocations(request, actor_ref: str) -> None:
    """Idempotent: one obligation per kind, and a revoke round queued (another is queued even while one runs, so a
    late fact is never a lost wakeup)."""
    for kind in ("setup_links", *MAILBOX_KINDS, *DOMAIN_KINDS):
        AccessRevocation.objects.get_or_create(request=request, kind=kind,
                                               defaults={"state": "verified" if kind == "setup_links" else "requested"})
    _queue_round(request)
    core.record(request.application, "provisioning_revocation_requested", {"request": str(request.public_id)}, actor_ref)


def _queue_round(request, due_in=None) -> bool:
    """Queue one revocation round unless one is already queued; True when it queued one."""
    if PendingAction.objects.filter(kind=REVOKE, input_ref=str(request.public_id), status=Status.QUEUED).exists():
        return False
    n = PendingAction.objects.filter(kind=REVOKE, input_ref=str(request.public_id)).count()
    core.enqueue(REVOKE, request, f"revoke:{request.public_id}:{n}", due_in=due_in)
    return True


FINAL = ("verified", "applied_unverified", "not_applicable", "exception")


def revocation_complete(request) -> bool:
    """Complete only for a settled request whose every obligation is verified, applied with its stated limit, not
    applicable, or an owner-accepted exception (023 11.6 and 11.11)."""
    rows = list(request.revocations.values_list("state", flat=True))
    queued_round = PendingAction.objects.filter(kind=REVOKE, input_ref=str(request.public_id),
                                                status__in=(Status.QUEUED, Status.RUNNING)).exists()
    return (bool(rows) and not _open_outcome(request) and not _reconciling(request) and not queued_round
            and all(s in FINAL for s in rows))


EXCEPTIONABLE = ("sessions", "app_credentials", "inbound_forwarders", "catch_all")


def accept_revocation_exception(revocation_id: int, user, reason: str) -> None:
    """The owner (the approver role, P5-D-3) accepts, with a reason, an obligation that cannot be completed: one with
    no documented mechanism, or a shared forwarder or catch-all staff could not change. A rotation or an owned
    forwarder is never waived."""
    services.require(user, "approve_provisioning")
    note = services._reason(reason)
    with transaction.atomic():
        row = AccessRevocation.objects.select_related("request").get(pk=revocation_id)
        core.lock(row.request.application_id, row.request_id)
        row = AccessRevocation.objects.select_for_update(of=("self",)).get(pk=revocation_id)
        if row.kind not in EXCEPTIONABLE or row.state not in ("unsupported", "pending"):
            raise services.Refused("not_exceptionable")
        AccessRevocation.objects.filter(pk=row.pk).update(state="exception", note=note, decided_by=services.actor(user),
                                                          updated_at=Now())
        journal.record("access_revocation", f"revocation:{row.request.public_id}:{row.kind}", {"state": "exception"})
        core.record(row.request.application, "provisioning_revocation_exception_accepted",
                    {"request": str(row.request.public_id), "kind": row.kind}, services.actor(user),
                    actor_type=ApplicationEvent.ActorType.STAFF)
        request = ProvisioningRequest.objects.get(pk=row.request_id)
        if revocation_complete(request):
            services._resolve(request, ITEM_REVOCATION, "revocation_complete", services.actor(user), note)


def recheck_revocation(request_id: int, user, reason: str) -> None:
    """Staff, after fixing a shared forwarder or the catch-all in the panel, ask for a new round: only a read can mark
    it verified."""
    services.require(user, "operate_provisioning")
    services._reason(reason)
    with transaction.atomic():
        application, request = core.lock(ProvisioningRequest.objects.get(pk=request_id).application_id, request_id)
        if request.stop_requested_at is None or not request.revocations.exists():
            raise services.Refused("nothing_to_revoke")
        if not PendingAction.objects.filter(kind=REVOKE, input_ref=str(request.public_id), status=Status.QUEUED).update(
                due_at=Now(), updated_at=Now()):  # bring a waiting round forward, or queue one
            _queue_round(request)


def _rotate(host, domain: str, local: str) -> str:
    """The rotation's random value lives only in this frame; any failure is reduced to a code with no traceback."""
    try:
        host.set_password(domain, local, secrets.token_urlsafe(32))
        return ""
    except adapter.AdapterError as exc:
        return exc.code
    except Exception as exc:
        logger.error("rotation raised %s", type(exc).__name__)
        return "adapter_error"


class RevokeAccess(_Action):
    kind = REVOKE

    def run(self, claim) -> None:
        request = self._request(claim)
        if request is None or request.stop_requested_at is None:
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_revoke")
            return
        key = self._key(claim)
        n = int(key.rsplit(":", 1)[-1]) if key.rsplit(":", 1)[-1].isdigit() else 0
        grace = timedelta(seconds=settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS)
        if request.setups.filter(state="set_pending").exists():
            # 023 11.5: never rotate under a password set in flight; look again after its timeout.
            ledger.finish(claim, self, status=Status.QUEUED, error="set_pending", refund_attempt=True,
                          due_in=timedelta(seconds=settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS + 1))
            return
        if _open_outcome(request) or _reconciling(request):  # a create, reconcile or watch is still open
            if _reconciling(request):  # reconciliation or the watch will settle it: look again then
                ledger.finish(claim, self, status=Status.QUEUED, error="not_settled", refund_attempt=True, due_in=grace)
            else:
                ledger.finish(claim, self, status=Status.DONE, error="not_settled",
                              write=lambda: core.item(ITEM_REVOCATION, request, claim_id=claim.id))
            return
        ours = proven_ours(request) and not refused_as_foreign(request)
        if not ours and unproven_present(request):
            # A mailbox may exist but is not proven ours: staff confirm or refuse it first (never act on a foreign one).
            ledger.finish(claim, self, status=Status.DONE, error="not_proven_ours",
                          write=lambda: core.item(ITEM_REVOCATION, request, claim_id=claim.id))
            return
        domain, local = request.reservation.domain, request.reservation.local_part
        address = f"{local}@{domain}".lower()
        outcomes, removed = {}, []
        if not ours:  # settled, and no mailbox of ours ever existed
            outcomes = {k: "not_applicable" for k in (*MAILBOX_KINDS, *DOMAIN_KINDS)}
        else:
            try:
                host = adapter.host()
                mailbox = host.read(domain, local)
                if mailbox is None:
                    outcomes.update({k: "not_applicable" for k in MAILBOX_KINDS})
                else:
                    code = _rotate(host, domain, local)
                    if code:
                        raise adapter.AdapterError(code, sent=True)
                    outcomes["password_rotation"] = "applied_unverified"
                    for alias, dests in host.list_forwarders(domain):
                        if alias.lower() == local.lower():
                            host.delete_forwarder(domain, alias)
                            removed.append({"alias": alias, "destinations_sha256": hashlib.sha256(
                                "\n".join(sorted(d.lower() for d in dests)).encode()).hexdigest()})
                    owned = [a for a, _ in host.list_forwarders(domain) if a.lower() == local.lower()]
                    outcomes["owned_forwarders"] = "verified" if not owned else "pending"
                    outcomes["sessions"] = outcomes["app_credentials"] = "unsupported"
                inbound = [a for a, dests in host.list_forwarders(domain) if any(d.lower() == address for d in dests)]
                outcomes["inbound_forwarders"] = "pending" if inbound else "verified"  # shared: staff decide (11.11)
                outcomes["catch_all"] = "pending" if host.read_catch_all(domain).lower() == address else "verified"
            except adapter.AdapterError as exc:
                self._retry_or_staff(claim, request, f"revoke_{exc.code}", staff_status=request.status)
                return

        def write():
            current = ProvisioningRequest.objects.select_related("application").get(pk=request.pk)
            for kind, state in outcomes.items():
                AccessRevocation.objects.filter(request=current, kind=kind).exclude(state__in=FINAL).exclude(
                    state=state).update(state=state, updated_at=Now())
                if state in FINAL:  # 9kg.33: an access removal that happened is a fact the restore must keep
                    journal.record("access_revocation", f"revocation:{current.public_id}:{kind}", {"state": state})
            for forwarder in removed:  # what was removed, as identifiers and a digest of its destinations
                core.record(current.application, "provisioning_forwarder_removed",
                            {"request": str(current.public_id), **forwarder}, f"pending_action:{claim.id}")
            if any(s in ("pending", "unsupported") for s in outcomes.values()):
                core.item(ITEM_REVOCATION, current, claim_id=claim.id)
            if outcomes.get("password_rotation") == "applied_unverified" and ":repeat:" not in key:
                # one repeat after a settle delay, so no late password write outlives the revocation (023 11.5)
                core.enqueue(REVOKE, current, f"revoke:{current.public_id}:repeat:{claim.id}",
                             due_in=timedelta(seconds=settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS + 1))
            if revocation_complete(current):  # the ledger has already marked this round done, so it does not count
                services._resolve(current, ITEM_REVOCATION, "revocation_complete", f"pending_action:{claim.id}")
            core.record(current.application, "provisioning_revocation_run", {"request": str(current.public_id),
                                                                             "round": n}, f"pending_action:{claim.id}")
        ledger.finish(claim, self, status=Status.DONE, write=write)


# --- the applicant's withdrawal (P5-D-8) ---------------------------------------------------------------------------

def request_withdrawal_link(application_id: int, user, reason: str) -> WithdrawalConfirmation:
    """Staff, on the applicant's request (an email asking to withdraw is a review item, never a withdrawal), send a
    one-time confirmation link to the verified address."""
    services.require(user, "close_application")
    note = services._reason(reason)
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        if application.stage in TERMINAL_STAGES:
            raise services.Refused("already_closed")
        recipient = verified_address(application)
        if not recipient:
            raise services.Refused("contact_not_verified")
        WithdrawalConfirmation.objects.filter(application=application, state__in=("pending", "sent", "uncertain")).update(
            state="superseded", updated_at=Now())  # an in-flight send's late result then matches nothing
        row = WithdrawalConfirmation.objects.create(application=application, recipient=recipient,
                                                    requested_by=services.actor(user))
        core.record(application, "provisioning_withdrawal_link_requested",
                    {"confirmation": str(row.public_id), "reason": note}, services.actor(user),
                    actor_type=ApplicationEvent.ActorType.STAFF)
        PendingAction.objects.create(kind=WITHDRAW_SEND, subject_type="application", subject_id=application.public_ref,
                                     input_ref=str(row.public_id), idempotency_key=f"withdraw_send:{row.public_id}",
                                     max_attempts=settings.CATALYST_PROVISIONING_ATTEMPTS)
    return row


class SendWithdrawalLink(_Action):
    """The worker mints the token at send time and stores only its hash, as for the setup invitation. An uncertain
    send leaves the row `uncertain` and opens a staff item; staff request a new link."""

    kind = WITHDRAW_SEND
    automated = False  # the applicant's own request to leave: a pause never holds it
    redeliverable = False

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        from correspondence.staff_items import event, open_item

        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            open_item(ITEM_WITHDRAWAL, f"withdrawal:{claim.input_ref}", application=application, pending_action_id=claim.id)

    def run(self, claim) -> None:
        with transaction.atomic():
            Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
            row = WithdrawalConfirmation.objects.select_for_update(of=("self",)).select_related("application").filter(
                public_id=claim.input_ref).first()
            ledger.fence(claim)
            if row is None or row.state != "pending" or row.application.stage in TERMINAL_STAGES or \
                    verified_address(row.application) != row.recipient:
                ledger.finish(claim, self, status=Status.DONE, error="nothing_to_send")
                return
            WithdrawalConfirmation.objects.filter(pk=row.pk).update(state="uncertain", updated_at=Now())
        token = secrets.token_urlsafe(32)
        digest = _hash(token)
        message = EmailMessage(subject=SUBJECT, to=[row.recipient],
                               body=BODY.format(name=row.application.display_name,
                                                link=f"{settings.CATALYST_PUBLIC_BASE_URL}{WITHDRAW_PATH}{token}/"),
                               headers={"Message-ID": make_msgid(domain=urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname)})
        try:
            sent = message.send(fail_silently=False) == 1
        except Exception as exc:
            logger.warning("action %s: withdrawal link send failed (%s)", claim.id, type(exc).__name__)
            sent = False
        del token, message

        def write():
            if sent:
                WithdrawalConfirmation.objects.filter(pk=row.pk, state="uncertain").update(
                    state="sent", token_sha256=digest, updated_at=Now(),
                    expires_at=Now() + timedelta(seconds=settings.CATALYST_SETUP_LINK_SECONDS))
            else:
                from correspondence.staff_items import open_item

                open_item(ITEM_WITHDRAWAL, f"withdrawal:{row.public_id}", application=row.application,
                          pending_action_id=claim.id)
        try:
            ledger.finish(claim, self, status=Status.DONE, error="" if sent else "send_uncertain", write=write)
        except Exception as exc:
            raise ledger.LeftForRecovery from exc


def live_withdrawal(token: str):
    if not token or len(token) > 100:
        return None
    row = WithdrawalConfirmation.objects.select_related("application").filter(token_sha256=_hash(token),
                                                                               state="sent").first()
    if row is None or row.application.stage in TERMINAL_STAGES or verified_address(row.application) != row.recipient:
        return None
    if WithdrawalConfirmation.objects.filter(pk=row.pk, expires_at__lte=Now()).exists():
        return None
    return row


def confirm_withdrawal(token: str) -> bool:
    row = live_withdrawal(token)
    if row is None:
        return False
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=row.application_id)
        row = WithdrawalConfirmation.objects.select_for_update(of=("self",)).get(pk=row.pk)
        if row.state != "sent" or row.token_sha256 != _hash(token) or application.stage in TERMINAL_STAGES or \
                WithdrawalConfirmation.objects.filter(pk=row.pk, expires_at__lte=Now()).exists() or \
                verified_address(application) != row.recipient:
            return False
        WithdrawalConfirmation.objects.filter(pk=row.pk).update(state="used", updated_at=Now())
        try:
            close_locked(application, "withdrawn", f"applicant confirmed through link {row.public_id}", "applicant",
                         ApplicationEvent.ActorType.APPLICANT)
        except services.Refused:
            transaction.set_rollback(True)
            refused = True
        else:
            refused = False
    if refused:  # never a server error: the same closed page, and staff are told
        from correspondence.staff_items import open_item

        open_item(ITEM_WITHDRAWAL, f"withdrawal:{row.public_id}", application=row.application)
        return False
    return True
