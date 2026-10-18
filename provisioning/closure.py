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
from workflow import ledger
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
    for request in ProvisioningRequest.objects.select_for_update(of=("self",)).filter(
            application=application, status__in=(*LIVE_REQUEST, "active")):
        status = "stopping" if request.status in ("create_pending", "create_uncertain") else "stopped"
        may_exist = services._mailbox_may_exist(request) or request.status == "active"
        ProvisioningRequest.objects.filter(pk=request.pk).update(status=status, stop_requested_at=Now(),
                                                                 updated_at=Now())
        PendingAction.objects.filter(input_ref=str(request.public_id), status__in=(Status.QUEUED, Status.HELD),
                                     kind__in=(core.CREATE, "provision_invite", "provision_activate")).update(
            status=Status.CANCELLED, completed_at=Now(), updated_at=Now(), last_error="application_closed")
        CredentialSetup.objects.filter(request=request, state__in=("invitation_pending", "invited", "presented")).update(
            state="cancelled", updated_at=Now())
        request.refresh_from_db()
        if may_exist:
            ensure_revocations(request, actor_ref)
    PendingAction.objects.filter(kind=core.HANDOFF, subject_id=application.public_ref, status=Status.HELD).update(
        status=Status.CANCELLED, completed_at=Now(), updated_at=Now(), last_error="application_closed")
    to = Stage.WITHDRAWN if outcome == "withdrawn" else Stage.CLOSED
    transition(application.pk, (application.stage,), to, event_kind=f"application_{outcome}",
               data={"reason": reason}, actor_type=actor_type, actor_ref=actor_ref)


def close_application(application_id: int, user, outcome: str, reason: str) -> None:
    services.require(user, "close_application")
    note = services._reason(reason)
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        close_locked(application, outcome, note, services.actor(user), ApplicationEvent.ActorType.STAFF)


# --- revocation obligations ---------------------------------------------------------------------------------------

def ensure_revocations(request, actor_ref: str) -> None:
    """Idempotent: one obligation per kind; the revoke action is queued once per round."""
    for kind in ("setup_links", *MAILBOX_KINDS, *DOMAIN_KINDS):
        state = "verified" if kind == "setup_links" else "unsupported" if kind in ("sessions", "app_credentials") \
            else "requested"
        AccessRevocation.objects.get_or_create(request=request, kind=kind, defaults={"state": state})
    if AccessRevocation.objects.filter(request=request, state="unsupported").exists():
        core.item(ITEM_REVOCATION, request)  # sessions and app credentials: no documented mechanism (023 section 3)
    n = PendingAction.objects.filter(kind=REVOKE, input_ref=str(request.public_id)).count()
    if not PendingAction.objects.filter(kind=REVOKE, input_ref=str(request.public_id),
                                        status__in=(Status.QUEUED, Status.RUNNING)).exists():
        core.enqueue(REVOKE, request, f"revoke:{request.public_id}:{n}")
    core.record(request.application, "provisioning_revocation_requested", {"request": str(request.public_id)}, actor_ref)


def revocation_complete(request) -> bool:
    """Complete only when every obligation is verified, applied (with its stated limit), not applicable, or an
    owner-accepted exception."""
    rows = list(request.revocations.values_list("state", flat=True))
    return bool(rows) and all(s in ("verified", "applied_unverified", "not_applicable", "exception") for s in rows)


def accept_revocation_exception(revocation_id: int, user, reason: str) -> None:
    """The owner (the approver role, P5-D-3) accepts, with a reason, an obligation that cannot be completed."""
    services.require(user, "approve_provisioning")
    note = services._reason(reason)
    with transaction.atomic():
        row = AccessRevocation.objects.select_related("request").get(pk=revocation_id)
        core.lock(row.request.application_id, row.request_id)
        row = AccessRevocation.objects.select_for_update(of=("self",)).get(pk=revocation_id)
        if row.state not in ("unsupported", "pending", "requested"):
            raise services.Refused("not_open")
        AccessRevocation.objects.filter(pk=row.pk).update(state="exception", note=note, decided_by=services.actor(user),
                                                          updated_at=Now())
        core.record(row.request.application, "provisioning_revocation_exception_accepted",
                    {"request": str(row.request.public_id), "kind": row.kind}, services.actor(user),
                    actor_type=ApplicationEvent.ActorType.STAFF)


class RevokeAccess(_Action):
    kind = REVOKE

    def run(self, claim) -> None:
        request = self._request(claim)
        if request is None or request.stop_requested_at is None:
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_revoke")
            return
        key = self._key(claim)
        n = int(key.rsplit(":", 1)[-1]) if key.rsplit(":", 1)[-1].isdigit() else 0
        if request.setups.filter(state="set_pending").exists():
            # 023 11.5: never rotate under a password set in flight; look again after its timeout.
            ledger.finish(claim, self, status=Status.QUEUED, error="set_pending", refund_attempt=True,
                          due_in=timedelta(seconds=settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS + 1))
            return
        domain, local = request.reservation.domain, request.reservation.local_part
        address = f"{local}@{domain}".lower()
        try:
            host = adapter.host()
            mailbox = host.read(domain, local)
            outcomes = {}
            if mailbox is None:
                outcomes.update({k: "not_applicable" for k in MAILBOX_KINDS if k not in ("sessions", "app_credentials")})
            else:
                host.set_password(domain, local, secrets.token_urlsafe(32))  # unknown to anyone, never stored
                outcomes["password_rotation"] = "applied_unverified"
                for alias, _ in host.list_forwarders(domain):
                    if alias.lower() == local.lower():
                        host.delete_forwarder(domain, alias)
                owned = [a for a, _ in host.list_forwarders(domain) if a.lower() == local.lower()]
                outcomes["owned_forwarders"] = "verified" if not owned else "pending"
            inbound = [a for a, dests in host.list_forwarders(domain) if any(d.lower() == address for d in dests)]
            outcomes["inbound_forwarders"] = "pending" if inbound else "verified"  # shared: staff decide (11.11)
            outcomes["catch_all"] = "pending" if host.read_catch_all(domain).lower() == address else "verified"
        except adapter.AdapterError as exc:
            self._retry_or_staff(claim, request, f"revoke_{exc.code}", staff_status=request.status)
            return

        def write():
            current = ProvisioningRequest.objects.select_related("application").get(pk=request.pk)
            for kind, state in outcomes.items():
                AccessRevocation.objects.filter(request=current, kind=kind).exclude(
                    state__in=("verified", "not_applicable", "exception")).update(state=state, updated_at=Now())
            if any(s == "pending" for s in outcomes.values()):
                core.item(ITEM_REVOCATION, current, claim_id=claim.id)
            if mailbox is not None and n == 0:  # one repeat after a settle delay, so no late write outlives it
                core.enqueue(REVOKE, current, f"revoke:{current.public_id}:{n + 1}",
                             due_in=timedelta(seconds=settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS + 1))
            core.record(current.application, "provisioning_revocation_run", {"request": str(current.public_id),
                                                                             "round": n}, f"pending_action:{claim.id}")
        ledger.finish(claim, self, status=Status.DONE, write=write)


# --- the applicant's withdrawal (P5-D-8) ---------------------------------------------------------------------------

def request_withdrawal_link(application_id: int, user, reason: str) -> WithdrawalConfirmation:
    """Staff, on the applicant's request (an email asking to withdraw is a review item, never a withdrawal), send a
    one-time confirmation link to the verified address."""
    services.require(user, "close_application")
    services._reason(reason)
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
        if application.stage in TERMINAL_STAGES:
            raise services.Refused("already_closed")
        recipient = verified_address(application)
        if not recipient:
            raise services.Refused("contact_not_verified")
        WithdrawalConfirmation.objects.filter(application=application, state__in=("pending", "sent")).update(
            state="superseded", updated_at=Now())
        row = WithdrawalConfirmation.objects.create(application=application, recipient=recipient,
                                                    requested_by=services.actor(user))
        PendingAction.objects.create(kind=WITHDRAW_SEND, subject_type="application", subject_id=application.public_ref,
                                     input_ref=str(row.public_id), idempotency_key=f"withdraw_send:{row.public_id}",
                                     max_attempts=settings.CATALYST_PROVISIONING_ATTEMPTS)
    return row


class SendWithdrawalLink(_Action):
    """The worker mints the token at send time and stores only its hash, as for the setup invitation. An uncertain
    send leaves the row `uncertain` and opens a staff item; staff request a new link."""

    kind = WITHDRAW_SEND
    automated = True
    redeliverable = False

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

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
        close_locked(application, "withdrawn", "applicant confirmed through the verified link", "applicant",
                     ApplicationEvent.ActorType.APPLICANT)
    return True
