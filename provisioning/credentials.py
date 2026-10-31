"""P5 5B.2: the set-your-own-password flow and activation (023 sections 5 steps 6 and 7, 11.2, 11.5, 11.7, 11.8 and
11.11; P5-D-6). Synthetic only: the credential operation is the fake behind `provisioning.adapter`.

- `open_setup` (inside the caller's transaction): a verified mailbox opens a setup series and queues its invitation.
- `SendSetupInvitation` (`provision_invite`, automated): the worker mints the token at send time, sends the link to
  the previously verified external address and stores only the token's SHA-256, once. An uncertain send is never
  reconciled: the series is superseded and a new one mints a new token, up to `CATALYST_SETUP_INVITE_MAX_SERIES`, then
  staff decide.
- `set_password` (the applicant's POST): a compare-and-set to `set_pending` and commit; the credential operation
  outside any lock, with the password only in memory; a second transaction records the result. A definite rejection
  returns to `presented` for another choice (bounded); an unknown outcome is `set_uncertain`, which is never read back
  and is recovered by a new invitation.
- `SweepSetup` (`provision_setup_sweep`, protective): a `set_pending` older than the operation timeout becomes
  `set_uncertain`.
- `Activate` (`provision_activate`, automated): B6's fresh Documenso read, then in one transaction the prerequisites,
  verified provisioning and a completed setup; the stage `provisioning -> active`, and the approved welcome is frozen
  and queued for the P2 sender, which sends later, outside the transaction.

"Invitation accepted by the mail server", "link presented", "credential set" and "access ready" are four facts;
only the last allows activation.
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
from django.views.decorators.debug import sensitive_variables

from applications.links import SETUP_PATH
from applications.models import Application, Stage
from applications.stages import transition
from config.mail import from_header, reply_to
from correspondence.messages import verified_address
from workflow import ledger
from workflow.models import PendingAction

from . import adapter, core
from .handlers import _Action
from .models import LIVE_SETUP, CredentialSetup, ProvisioningRequest

logger = logging.getLogger(__name__)
Status = PendingAction.Status

INVITE = "provision_invite"
SWEEP = "provision_setup_sweep"  # also the expiry check of an unused link (key setup_expire:...)
ACTIVATE = "provision_activate"
WELCOME_TEMPLATE = "provisioning_welcome"
ITEM_SETUP = "provisioning_setup_needs_staff"
ITEM_ACTIVATION = "provisioning_activation_blocked"
SUBJECT = "Set the password for your new mailbox"
BODY = ("Hello {name},\n\nYour mailbox has been created. Choose its password here (the link works once and expires):\n\n"
        "{link}\n\nIf you did not expect this message, ignore it.\n")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def setup_link(token: str) -> str:
    return f"{settings.CATALYST_PUBLIC_BASE_URL}{SETUP_PATH}{token}/"


def _outside_company(address: str) -> bool:
    domain = settings.CATALYST_PROVISIONING_DOMAIN.lower()
    return bool(address) and not (domain and address.lower().rsplit("@", 1)[-1] == domain)


def recipient_problem(application, setup) -> str:
    """023 11.8: at send time and at redemption the recipient is still the current verified contact, outside the
    company domain."""
    current = verified_address(application)
    if not current or current != setup.recipient or not _outside_company(current):
        return "recipient_changed"
    return ""


def open_setup(request, actor_ref: str) -> CredentialSetup | None:
    """Inside the caller's transaction, with the application and request locked. The recipient is the verified
    external address now, never the new mailbox or any company-domain address."""
    if request.method != ProvisioningRequest.Method.API:
        # The set-your-own-password flow needs the API (P5-D-6 option a). On the checklist path the credential is
        # the owner's separately approved contingency (option b): staff are told, nothing is sent.
        core.item(ITEM_SETUP, request)
        return None
    recipient = verified_address(request.application)
    if not recipient or not _outside_company(recipient):
        core.item(ITEM_SETUP, request)
        return None
    series = request.setups.count()
    setup = CredentialSetup.objects.create(request=request, series=series, recipient=recipient)
    core.set_status(request, "setup_pending")
    core.enqueue(INVITE, request, f"setup_invite:{setup.public_id}:{series}")
    core.record(request.application, "provisioning_setup_opened", {"request": str(request.public_id), "series": series},
                actor_ref)
    return setup


def _supersede_and_reopen(setup, request, actor_ref: str, code: str) -> None:
    """A series that cannot be trusted any more is superseded; a new one opens, bounded, then staff decide."""
    CredentialSetup.objects.filter(pk=setup.pk, state__in=(*LIVE_SETUP, "invitation_uncertain", "set_uncertain")).update(
        state="superseded", updated_at=Now())
    core.record(request.application, "provisioning_setup_superseded", {"request": str(request.public_id),
                                                                       "series": setup.series, "code": code}, actor_ref)
    if request.status != "setup_pending":
        return  # superseded, stopped or otherwise moved on: a late sweep never reopens it
    if request.setups.count() >= settings.CATALYST_SETUP_INVITE_MAX_SERIES or request.stop_requested_at is not None:
        core.item(ITEM_SETUP, request)
        return
    open_setup(request, actor_ref)


# --- the invitation ---------------------------------------------------------------------------------------------

class SendSetupInvitation(_Action):
    kind = INVITE
    automated = True
    redeliverable = False  # a lost result is never repeated with the same token: the series is superseded

    def _setup(self, claim):
        key = self._key(claim)
        setup_id = key.split(":")[1] if key.count(":") >= 2 else ""
        return CredentialSetup.objects.select_related("request__application", "request__reservation").filter(
            public_id=setup_id).first() if setup_id else None

    def run(self, claim) -> None:
        setup = self._setup(claim)
        if setup is None:
            ledger.finish(claim, self, status=Status.DONE, error="no_setup")
            return
        try:
            with transaction.atomic():
                application, request = core.lock(setup.request.application_id, setup.request_id)
                setup = CredentialSetup.objects.select_for_update(of=("self",)).get(pk=setup.pk)
                ledger.fence(claim)
                if setup.state == "invitation_sending":  # a crash after the send: the outcome is unknown
                    CredentialSetup.objects.filter(pk=setup.pk).update(state="invitation_uncertain", updated_at=Now())
                    _supersede_and_reopen(setup, request, f"pending_action:{claim.id}", "earlier_send_unknown")
                    ledger.finish(claim, self, status=Status.DONE, error="earlier_send_unknown")
                    return
                if setup.state != "invitation_pending" or request.status != "setup_pending":
                    ledger.finish(claim, self, status=Status.DONE, error="nothing_to_send")
                    return
                problem = core.database_problem(application, request) or recipient_problem(application, setup)
                if problem:
                    CredentialSetup.objects.filter(pk=setup.pk).update(state="cancelled", updated_at=Now())
                    core.item(ITEM_SETUP, request, claim_id=claim.id)
                    ledger.finish(claim, self, status=Status.DONE, error=problem)
                    return
                CredentialSetup.objects.filter(pk=setup.pk).update(state="invitation_sending", updated_at=Now())
        except ledger.LeaseLost:
            return
        if transaction.get_connection().in_atomic_block:
            raise RuntimeError("refusing to send inside a transaction")
        token = secrets.token_urlsafe(32)  # minted now; only its hash is ever stored
        digest = token_hash(token)
        message = EmailMessage(
            subject=SUBJECT, to=[setup.recipient], from_email=from_header(), reply_to=reply_to(),
            body=BODY.format(name=setup.request.application.display_name, link=setup_link(token)),
            headers={"Message-ID": make_msgid(domain=urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname)})
        try:
            sent = message.send(fail_silently=False) == 1
        except Exception as exc:
            logger.warning("action %s: setup invitation send failed (%s)", claim.id, type(exc).__name__)
            sent = False
        del token, message
        try:
            ledger.finish(claim, self, status=Status.DONE, error="" if sent else "send_uncertain",
                          write=lambda: self._result(claim, setup, digest, sent))
        except Exception as exc:
            raise ledger.LeftForRecovery from exc

    def _result(self, claim, setup, digest, sent) -> None:
        setup = CredentialSetup.objects.select_related("request__application").get(pk=setup.pk)
        request = setup.request
        actor = f"pending_action:{claim.id}"
        if not sent:
            # Never reconciled by evidence: the old token (never stored) is dead; a new series mints a new one.
            CredentialSetup.objects.filter(pk=setup.pk).update(state="invitation_uncertain", updated_at=Now())
            _supersede_and_reopen(setup, request, actor, "send_uncertain")
            return
        if not CredentialSetup.objects.filter(pk=setup.pk, state="invitation_sending").update(
                state="invited", token_sha256=digest, updated_at=Now(),
                expires_at=Now() + timedelta(seconds=settings.CATALYST_SETUP_LINK_SECONDS)):
            return
        # An unused link ends visibly: at expiry it is `expired` and a new series opens (bounded), never a stall.
        core.enqueue(SWEEP, request, f"setup_expire:{setup.public_id}:0",
                     due_in=timedelta(seconds=settings.CATALYST_SETUP_LINK_SECONDS))
        core.record(request.application, "provisioning_setup_invited", {"request": str(request.public_id),
                                                                        "series": setup.series}, actor)


# --- the applicant's page ---------------------------------------------------------------------------------------

class SetupRefused(Exception):
    """One uniform refusal for an unknown, used, expired, cancelled or superseded link (no enumeration)."""


def live_setup(token: str):
    """The setup a token opens, or None. Never consumes the token (a GET or a link preview is harmless)."""
    if not token or len(token) > 100:
        return None
    setup = (CredentialSetup.objects.select_related("request__application", "request__reservation")
             .filter(token_sha256=token_hash(token), state__in=("invited", "presented")).first())
    if setup is None or setup.request.stop_requested_at is not None or setup.request.status != "setup_pending":
        return None
    if recipient_problem(setup.request.application, setup):
        return None
    if CredentialSetup.objects.filter(pk=setup.pk, expires_at__lte=Now()).exists():
        return None
    return setup


def mark_presented(setup) -> None:
    CredentialSetup.objects.filter(pk=setup.pk, state="invited").update(state="presented", updated_at=Now())


@sensitive_variables("password")
def set_password(token: str, password: str) -> str:
    """The protocol of 023 11.5. Returns "completed" or "retry" (a definite rejection: choose again), or raises
    SetupRefused. The password is never stored, logged or kept beyond this call."""
    setup = live_setup(token)
    if setup is None:
        raise SetupRefused
    if not (8 <= len(password) <= 72):
        return "retry"
    with transaction.atomic():
        application, request = core.lock(setup.request.application_id, setup.request_id)
        setup = CredentialSetup.objects.select_for_update(of=("self",)).get(pk=setup.pk)
        if (setup.state not in ("invited", "presented") or setup.token_sha256 != token_hash(token)
                or request.status != "setup_pending" or core.database_problem(application, request)
                or recipient_problem(application, setup)  # re-checked at redemption (023 11.8)
                or CredentialSetup.objects.filter(pk=setup.pk, expires_at__lte=Now()).exists()):
            raise SetupRefused
        CredentialSetup.objects.filter(pk=setup.pk).update(state="set_pending", set_started_at=Now(),
                                                           set_attempts=setup.set_attempts + 1, updated_at=Now())
        core.enqueue(SWEEP, request, f"setup_sweep:{setup.public_id}:{setup.set_attempts + 1}",
                     due_in=timedelta(seconds=settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS))
    try:
        adapter.host().set_password(request.reservation.domain, request.reservation.local_part, password)
        result = None
    except adapter.AdapterError as exc:
        result = adapter.AdapterError(exc.code, sent=exc.sent, status=exc.status)  # no traceback holds the password
        del exc
    except Exception as exc:
        logger.error("setup %s: the credential operation raised %s", setup.public_id, type(exc).__name__)
        result = adapter.AdapterError("handler_error", sent=True)
    del password
    outcome = "refused"
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        current = CredentialSetup.objects.select_for_update(of=("self",)).get(pk=setup.pk)
        if current.state != "set_pending":  # the sweep already called it uncertain: keep that
            outcome = "refused"
        elif result is None:
            CredentialSetup.objects.filter(pk=setup.pk).update(state="completed", completed_at=Now(), updated_at=Now())
            if request.stop_requested_at is None:
                core.set_status(request, "setup_complete")
                core.enqueue(ACTIVATE, request, f"activate:{request.public_id}")
            core.record(application, "provisioning_setup_completed", {"request": str(request.public_id)}, "applicant")
            outcome = "completed"
        elif not result.unknown and result.status == 400:  # the server refused this choice: choose again, bounded
            if current.set_attempts >= settings.CATALYST_SETUP_SET_ATTEMPTS:
                _supersede_and_reopen(current, request, "applicant", "set_attempts_exhausted")
                outcome = "refused"
            else:
                CredentialSetup.objects.filter(pk=setup.pk).update(state="presented", updated_at=Now())
                outcome = "retry"
        else:  # unknown: never read back; a new invitation lets the applicant choose again
            CredentialSetup.objects.filter(pk=setup.pk).update(state="set_uncertain", updated_at=Now())
            _supersede_and_reopen(current, request, "applicant", "set_uncertain")
            outcome = "refused"
    if outcome == "refused":  # raised after the commit, so the recorded outcome stands
        raise SetupRefused
    return outcome


class SweepSetup(_Action):
    """Protective. `setup_sweep:<setup>:<attempt>`: a `set_pending` of that same attempt, older than the operation
    timeout, is `set_uncertain` (never read back) and a new series opens. `setup_expire:<setup>:0`: an unused link
    past its expiry is `expired` and a new series opens. Both bounded by the series limit, then staff."""

    kind = SWEEP

    def run(self, claim) -> None:
        key = self._key(claim)
        mode, setup_id, n = (key.split(":") + ["", "", ""])[:3]

        def write():
            setup = CredentialSetup.objects.select_related("request__application").filter(public_id=setup_id).first()
            if setup is None:
                return
            actor = f"pending_action:{claim.id}"
            if mode == "setup_expire":
                if setup.state in ("invited", "presented") and CredentialSetup.objects.filter(
                        pk=setup.pk, expires_at__lte=Now()).exists():
                    CredentialSetup.objects.filter(pk=setup.pk).update(state="expired", updated_at=Now())
                    core.record(setup.request.application, "provisioning_setup_expired",
                                {"request": str(setup.request.public_id), "series": setup.series}, actor)
                    _reopen_after(setup, setup.request, actor)
                return
            timeout = timedelta(seconds=settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS)
            if (setup.state != "set_pending" or str(setup.set_attempts) != n
                    or not CredentialSetup.objects.filter(pk=setup.pk, set_started_at__lte=Now() - timeout).exists()):
                return  # a later attempt, or still within its time: not this sweep's business (security review)
            CredentialSetup.objects.filter(pk=setup.pk).update(state="set_uncertain", updated_at=Now())
            _supersede_and_reopen(setup, setup.request, actor, "set_timed_out")
        ledger.finish(claim, self, status=Status.DONE, write=write)


def _reopen_after(setup, request, actor_ref: str) -> None:
    """After an expired (terminal) series: open a new one within the bound, else staff."""
    if request.status != "setup_pending":
        return  # superseded, stopped or otherwise moved on: a late expiry never reopens it
    if request.setups.count() >= settings.CATALYST_SETUP_INVITE_MAX_SERIES or request.stop_requested_at is not None:
        core.item(ITEM_SETUP, request)
        return
    open_setup(request, actor_ref)


def reissue(request_id: int, user, reason: str) -> CredentialSetup:
    """Staff, with a reason, send a fresh link after the bound was reached, a link expired or a recipient changed:
    any live series is superseded first. Never replays an old link."""
    from correspondence.models import StaffItem
    from correspondence.staff_items import resolve_item

    from . import services

    services.require(user, "operate_provisioning")
    note = services._reason(reason)
    request = ProvisioningRequest.objects.get(pk=request_id)
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        if request.status not in ("setup_pending", "verified"):  # verified: no usable recipient when it was opened
            raise services.Refused("not_awaiting_setup")
        if request.method != ProvisioningRequest.Method.API:
            raise services.Refused("checklist_credential_is_a_separate_contingency")  # P5-D-6 option (b)
        problem = core.database_problem(application, request)
        if problem:
            raise services.Refused(problem)
        if request.setups.filter(state="set_pending").exists():
            raise services.Refused("set_in_progress")
        if request.setups.filter(state="invitation_sending").exists():
            raise services.Refused("invitation_in_flight")
        request.setups.filter(state__in=("invitation_pending", "invited", "presented")).update(
            state="superseded", updated_at=Now())
        setup = open_setup(request, services.actor(user))
        if setup is None:
            raise services.Refused("recipient_not_usable")
        for open_one in StaffItem.objects.filter(reason_code=ITEM_SETUP, dedupe_key=f"provisioning:{request.public_id}",
                                                 status=StaffItem.Status.OPEN):
            resolve_item(open_one, code="reissued", actor_ref=services.actor(user), note=note)
    return setup


# --- activation -------------------------------------------------------------------------------------------------

class Activate(_Action):
    kind = ACTIVATE
    automated = True
    redeliverable = True  # one transaction, idempotent by the stage compare-and-set

    def run(self, claim) -> None:
        from agreements.completion import fresh_read_problem

        request = self._request(claim)
        if request is None or request.status != "setup_complete":
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_activate")
            return
        problem = fresh_read_problem(request.application)  # B6, outside any transaction
        if problem == "provider_unavailable":
            ledger.finish(claim, self, status=Status.QUEUED, error=problem, refund_attempt=True,
                          due_in=timedelta(seconds=settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS))
            return
        ledger.finish(claim, self, status=Status.DONE, error=problem, write=lambda: self._activate(claim, request, problem))

    def _activate(self, claim, request, fresh_problem) -> None:
        from correspondence.models import ApprovedMessage
        from correspondence.outbound import Refused, _freeze, current_template_version, enqueue_send
        from correspondence.rendering import TemplateRefused

        application = Application.objects.get(pk=request.application_id)
        request = ProvisioningRequest.objects.select_related("reservation").get(pk=request.pk)
        actor = f"pending_action:{claim.id}"
        if application.stage != Stage.PROVISIONING:
            return  # already active, or no longer provisioning: nothing more (the lock is held, so this stands)
        problem = fresh_problem or core.database_problem(application, request)
        completed = request.setups.filter(state="completed", completed_at__isnull=False).exists()
        verified = application.events.filter(kind="provisioning_verified", data__request=str(request.public_id)).exists()
        if not problem and (request.status != "setup_complete" or not (completed and verified)):
            problem = "not_ready"
        version = current_template_version(WELCOME_TEMPLATE)
        if not problem and version is None:
            problem = "no_approved_welcome_template"
        message = None
        if not problem:
            try:  # the welcome is frozen first: no activation without a welcome to send (security review)
                message = _freeze(application, ApprovedMessage.Kind.WELCOME, verified_address(application), version,
                                  {"display_name": application.display_name,
                                   "mailbox_address": request.reservation.address},
                                  actor, ApprovedMessage.Authority.SYSTEM_POLICY)
            except (Refused, TemplateRefused) as exc:
                problem = f"welcome_refused_{type(exc).__name__.lower()}"
        if problem:
            core.item(ITEM_ACTIVATION, request, claim_id=claim.id)
            core.record(application, "provisioning_activation_refused", {"request": str(request.public_id),
                                                                         "reason": problem}, actor)
            return
        transition(application.pk, (Stage.PROVISIONING,), Stage.ACTIVE, event_kind="provisioning_activated",
                   data={"request": str(request.public_id)}, actor_ref=actor)
        core.set_status(request, "active")
        enqueue_send(message, 0)  # the P2 sender sends it later, outside this transaction, with its own checks


def retry_activation(request_id: int, user, reason: str) -> None:
    """Staff, with a reason, run activation again once its cause is fixed (for example the owner approved the
    welcome template). Every check runs again; nothing is forced."""
    from correspondence.models import StaffItem
    from correspondence.staff_items import resolve_item

    from . import services

    services.require(user, "operate_provisioning")
    note = services._reason(reason)
    request = ProvisioningRequest.objects.get(pk=request_id)
    with transaction.atomic():
        application, request = core.lock(request.application_id, request.pk)
        if request.status != "setup_complete":
            raise services.Refused("not_ready")
        n = PendingAction.objects.filter(kind=ACTIVATE, input_ref=str(request.public_id)).count()
        core.enqueue(ACTIVATE, request, f"activate:{request.public_id}:{n}")
        for open_one in StaffItem.objects.filter(reason_code=ITEM_ACTIVATION, dedupe_key=f"provisioning:{request.public_id}",
                                                 status=StaffItem.Status.OPEN):
            resolve_item(open_one, code="retried", actor_ref=services.actor(user), note=note)
