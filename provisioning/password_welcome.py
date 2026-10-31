"""The one-time-password welcome: the first-generation alternative to the set-your-own-password link (034 row 39;
023 sections 11.5 and 11.8; bead catalyst-v2-bgl.10). Selected by `CATALYST_PROVISIONING_CREDENTIAL_MODE =
"one_time_password"`; P5-D-6's link flow stays the default and is untouched.

`SendPasswordWelcome` (`provision_welcome_password`, automated, never redelivered blindly) runs one credential series
(`CredentialSetup`, mode `one_time_password`) opened by `credentials.open_setup` after verification:

1. The check transaction, under the application and request locks: the series is still pending, the request is still
   `setup_pending`, the database prerequisites hold, the recipient is still the verified external address (never the
   new mailbox or a company address), an approved `provisioning_welcome_password` version exists and declares
   `$password`, and an IMAP host is configured. Any failure cancels the series before any provider call and tells
   staff. The series is committed `set_pending`, with the same sweep as the link flow.
2. Outside any transaction: a password generated here (letters and digits, all three classes, never stored), the
   documented password set at the host, an IMAP login as the new mailbox (implicit TLS, certificate verified), and
   only then the welcome, rendered in memory from the approved template and sent to the recipient. The password exists
   in this process's memory for the exchange only: no record, event, log, queue payload or Sent copy holds it (the
   template is secret-bearing, so `correspondence.outbound` can never freeze it into an ApprovedMessage either).
3. The fenced result transaction: `completed` (then `setup_complete` and activation, which sends no second welcome),
   or the series is superseded with its reason and a new one opens, bounded by `CATALYST_SETUP_INVITE_MAX_SERIES`,
   then staff decide. An unknown set, a failed or unreachable login check and an uncertain send are never replayed:
   the next round sets a new password, so a credential whose delivery is in doubt stops working.

Staff `reissue` opens a new round the same way: a resent welcome resets the password (the first-generation
`--confirm-password-reset`), which the required reason records.
"""

import logging
import secrets
import string
from datetime import timedelta
from email.utils import make_msgid
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models.functions import Now
from django.views.decorators.debug import sensitive_variables

from correspondence.outbound import current_template_version
from correspondence.rendering import TemplateRefused, render
from workflow import ledger
from workflow.models import PendingAction

from . import adapter, core, mxroute
from .credentials import ACTIVATE, ITEM_SETUP, ONE_TIME_PASSWORD, OTP_WELCOME, SWEEP, _supersede_and_reopen, recipient_problem
from .handlers import _Action
from .models import CredentialSetup

logger = logging.getLogger(__name__)
Status = PendingAction.Status

TEMPLATE = "provisioning_welcome_password"
VARIABLES = frozenset({"display_name", "mailbox_address", "mailbox_username", "password"})  # what a version may declare
PASSWORD_LENGTH = 20
ALPHABET = string.ascii_letters + string.digits
UNCERTAIN = ("password_set_uncertain", "welcome_send_uncertain")


def generate_password() -> str:
    """A strong initial password from `secrets`: letters and digits, at least one lower-case letter, one upper-case
    letter and one digit (the classes a mail host commonly requires), within the documented 8 to 72 characters."""
    while True:
        candidate = "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_LENGTH))
        if any(c.islower() for c in candidate) and any(c.isupper() for c in candidate) and any(c.isdigit() for c in candidate):
            return candidate


def template_problem(version) -> str:
    """Why the approved version cannot carry a one-time password, or "". Checked before any provider call: a welcome
    without `$password` would set a credential nobody receives."""
    if version is None:
        return "no_approved_password_welcome_template"
    declared = set(version.variables)
    if "password" not in declared:
        return "welcome_template_lacks_password"
    if not declared <= VARIABLES:
        return "welcome_template_variable_unknown"
    if not version.secret_bearing:
        return "welcome_template_not_secret_bearing"
    return ""


class SendPasswordWelcome(_Action):
    kind = OTP_WELCOME
    automated = True
    redeliverable = False  # a lost result is never repeated with the same password: the series is superseded

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
        version = current_template_version(TEMPLATE)  # an approved version is final (9kg.1), so it is safe to read here
        actor = f"pending_action:{claim.id}"
        try:
            with transaction.atomic():
                application, request = core.lock(setup.request.application_id, setup.request_id)
                setup = CredentialSetup.objects.select_for_update(of=("self",)).get(pk=setup.pk)
                ledger.fence(claim)
                if setup.state == "set_pending":  # a crash during the exchange: the password may be set, the welcome gone
                    CredentialSetup.objects.filter(pk=setup.pk).update(state="set_uncertain", updated_at=Now())
                    _supersede_and_reopen(setup, request, actor, "earlier_exchange_unknown")
                    ledger.finish(claim, self, status=Status.DONE, error="earlier_exchange_unknown")
                    return
                if setup.mode != ONE_TIME_PASSWORD or setup.state != "invitation_pending" or request.status != "setup_pending":
                    ledger.finish(claim, self, status=Status.DONE, error="nothing_to_send")
                    return
                problem = (core.database_problem(application, request) or recipient_problem(application, setup)
                           or template_problem(version)
                           or ("imap_not_configured" if not settings.CATALYST_PROVISIONING_IMAP_HOST else ""))
                if problem:
                    CredentialSetup.objects.filter(pk=setup.pk).update(state="cancelled", updated_at=Now())
                    core.item(ITEM_SETUP, request, claim_id=claim.id)
                    core.record(application, "provisioning_welcome_password_refused",
                                {"request": str(request.public_id), "series": setup.series, "reason": problem}, actor)
                    ledger.finish(claim, self, status=Status.DONE, error=problem)
                    return
                attempt = setup.set_attempts + 1
                CredentialSetup.objects.filter(pk=setup.pk).update(state="set_pending", set_started_at=Now(),
                                                                   set_attempts=attempt, updated_at=Now())
                core.enqueue(SWEEP, request, f"setup_sweep:{setup.public_id}:{attempt}",
                             due_in=timedelta(seconds=settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS))
        except ledger.LeaseLost:
            return
        if transaction.get_connection().in_atomic_block:
            raise RuntimeError("refusing to call the mail host inside a transaction")
        try:  # a defect from here on leaves the action running until its lease ends: the next run treats the round as unknown
            code = self._exchange(setup, version)
            ledger.finish(claim, self, status=Status.DONE, error=code, write=lambda: self._result(claim, setup, code))
        except Exception as exc:
            raise ledger.LeftForRecovery from exc

    @sensitive_variables("password", "values", "body", "message")
    def _exchange(self, setup, version) -> str:
        """Set the password, check the login, send the welcome. Returns "" or a reason code. The password is a local of
        this frame only; every exception is reduced to a code or a class name before it leaves."""
        reservation = setup.request.reservation
        domain, local = reservation.domain, reservation.local_part
        password = generate_password()
        try:
            adapter.host().set_password(domain, local, password)
        except adapter.AdapterError as exc:
            return "password_set_uncertain" if exc.unknown else f"password_set_rejected_{exc.code}"
        except Exception as exc:  # a defect during the exchange: the request may have left
            logger.error("setup %s: the credential operation raised %s", setup.public_id, type(exc).__name__)
            return "password_set_uncertain"
        try:
            accepted = mxroute.login_check(f"{local}@{domain}", password)
        except adapter.AdapterError as exc:
            return f"login_check_{exc.code}"  # could not check: the password is set, so this round ends and a new one sets another
        except Exception as exc:
            logger.error("setup %s: the login check raised %s", setup.public_id, type(exc).__name__)
            return "login_check_error"
        if not accepted:
            return "login_check_failed"
        available = {"display_name": setup.request.application.display_name, "mailbox_address": reservation.address,
                     "mailbox_username": local, "password": password}
        values = {name: available[name] for name in version.variables}
        try:
            subject, body = render(version, values)
        except TemplateRefused as refused:
            return f"welcome_{refused}"
        finally:
            del values, password
        message = EmailMessage(subject=subject, to=[setup.recipient], body=body,
                               headers={"Message-ID": make_msgid(domain=urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname)})
        del body
        try:
            sent = message.send(fail_silently=False) == 1
        except Exception as exc:
            logger.warning("setup %s: the welcome send failed (%s)", setup.public_id, type(exc).__name__)
            sent = False
        del message
        return "" if sent else "welcome_send_uncertain"

    def _result(self, claim, setup, code: str) -> None:
        setup = CredentialSetup.objects.select_related("request__application").get(pk=setup.pk)
        request = setup.request
        actor = f"pending_action:{claim.id}"
        if setup.state != "set_pending":
            return  # the sweep already called this round uncertain and superseded it: keep that
        if not code:
            CredentialSetup.objects.filter(pk=setup.pk).update(state="completed", completed_at=Now(), updated_at=Now())
            if request.stop_requested_at is None:
                core.set_status(request, "setup_complete")
                core.enqueue(ACTIVATE, request, f"activate:{request.public_id}")
            core.record(request.application, "provisioning_welcome_password_sent",
                        {"request": str(request.public_id), "series": setup.series}, actor)
            return
        if code in UNCERTAIN or code.startswith("login_check_"):
            # The password may be set and the welcome may have gone: never replayed; the next round sets a new one.
            CredentialSetup.objects.filter(pk=setup.pk).update(state="set_uncertain", updated_at=Now())
        _supersede_and_reopen(setup, request, actor, code)
