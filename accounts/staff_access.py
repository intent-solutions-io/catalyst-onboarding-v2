"""Staff access (026 section 8, P6-D-3; 6B.9): two-factor, login throttling, an absolute session lifetime, and the
scheduled removal of expired sessions.

- **Two-factor** (django-otp, TOTP plus single-use recovery codes). Outside the local environments every request under
  `/staff/` (the admin and every focused staff view, today's and any added later) needs a session verified by a
  second factor; an unverified or expired session is signed out and sent to the login page. The login form asks for
  the token. There is no self-service: the owner enrols a device (`manage.py enroll_staff_two_factor`) and, for a
  lost device, runs the break-glass reset (`manage.py reset_staff_two_factor`), exactly as the owner already sets
  passwords. There is no password-reset path at all (the admin's is refused in config.staff_admin).
- **Throttling:** password failures are counted per username in PostgreSQL (shared by every web process); after
  CATALYST_STAFF_LOGIN_FAILURE_LIMIT failures that username is refused for CATALYST_STAFF_LOGIN_LOCK_SECONDS, even
  with the right password. Only a hash of the username is stored. Token failures are throttled per device by
  django-otp itself.
- **Lifetimes:** the idle timeout is the 30-minute sliding session (config.settings); the absolute lifetime is
  checked here from the login time recorded in the session (PR #61 review).
- **Clean-up:** `clear_sessions` is a ledger action that removes expired session rows and day-old throttle rows,
  and queues its successor.
"""

import hashlib
import logging
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.views import redirect_to_login
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Now
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django_otp.admin import OTPAdminAuthenticationForm

logger = logging.getLogger("accounts.staff_access")

STAFF_PREFIX = "/staff/"
LOGIN_AT = "catalyst_login_at"
CLEAR_SESSIONS = "clear_sessions"
CLEANUP_SUBJECT = ("system", uuid.UUID("00000000-0000-0000-0000-00000000bbbb"))


def two_factor_required() -> bool:
    return settings.CATALYST_STAFF_TWO_FACTOR


@receiver(user_logged_in, dispatch_uid="catalyst_record_login_time")
def record_login_time(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        request.session[LOGIN_AT] = int(time.time())


class StaffAccess:
    """After django_otp's OTPMiddleware: signs out a staff session that has outlived its absolute lifetime, or that
    was never verified by a second factor where one is required, and sends it to the login page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith(STAFF_PREFIX):  # path_info: a script prefix can never move the gate
            login_url = reverse("admin:login")
            if not request.user.is_authenticated:
                # Only the login page answers an anonymous request, so a staff view added later without its own
                # check is still closed (PR review of 6B.9).
                if request.path != login_url:
                    return redirect_to_login(request.get_full_path(), login_url)
            else:
                reason = self.refusal(request)
                if reason is not None:
                    logger.info("staff session ended: %s", reason)
                    logout(request)
                    return redirect_to_login(request.get_full_path(), login_url)
        return self.get_response(request)

    @staticmethod
    def refusal(request) -> str | None:
        login_at = request.session.get(LOGIN_AT)
        if not isinstance(login_at, int) or time.time() - login_at > settings.CATALYST_STAFF_SESSION_MAX_SECONDS:
            return "absolute_lifetime"
        if two_factor_required() and not request.user.is_verified():
            return "not_verified"
        return None


class StaffLoginForm(OTPAdminAuthenticationForm):
    """The admin login form: password, then the token from an enrolled device, where two-factor is required."""

    def clean(self):
        if two_factor_required():
            return super().clean()
        return AdminAuthenticationForm.clean(self)


def throttle_key(username) -> str:
    return hashlib.sha256(str(username or "").casefold().encode()).hexdigest()


class ThrottledModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        from accounts.models import LoginThrottle

        key = throttle_key(username if username is not None else kwargs.get("username"))
        if LoginThrottle.objects.filter(key=key, locked_until__gt=Now()).exists():
            # Refused without checking the password, so a guess during the lock learns nothing; a hash is still
            # computed so a locked username answers no faster than an open one.
            get_user_model()().set_password(password or "")
            return None
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None:
            record_failure(key)
        else:
            LoginThrottle.objects.filter(key=key).update(failures=0, locked_until=None, updated_at=Now())
        return user


def record_failure(key: str) -> None:
    from accounts.models import LoginThrottle

    with transaction.atomic():
        try:
            with transaction.atomic():
                LoginThrottle.objects.create(key=key)
        except IntegrityError:
            pass  # another request created it first
        LoginThrottle.objects.filter(key=key).update(failures=F("failures") + 1, updated_at=Now())
        locked = LoginThrottle.objects.filter(key=key, failures__gte=settings.CATALYST_STAFF_LOGIN_FAILURE_LIMIT).update(
            failures=0, locked_until=Now() + timedelta(seconds=settings.CATALYST_STAFF_LOGIN_LOCK_SECONDS))
    if locked:
        logger.warning("staff login locked after repeated failures")


# --- scheduled session clean-up -----------------------------------------------------------------------------

def _cleanup_key(n: int) -> str:
    return f"{CLEAR_SESSIONS}:{n}"


def schedule_session_cleanup(n: int | None = None, delay: float = 0.0) -> bool:
    """Queue the next clean-up unless one is already queued or running; True when it queued one. Idempotent."""
    from workflow.models import PendingAction

    active = PendingAction.objects.filter(kind=CLEAR_SESSIONS, status__in=(PendingAction.Status.QUEUED,
                                                                            PendingAction.Status.RUNNING))
    if n is None and active.exists():
        return False
    n = n if n is not None else PendingAction.objects.filter(kind=CLEAR_SESSIONS).count() + 1
    try:
        with transaction.atomic():
            PendingAction.objects.create(kind=CLEAR_SESSIONS, subject_type=CLEANUP_SUBJECT[0],
                                         subject_id=CLEANUP_SUBJECT[1], input_ref="", idempotency_key=_cleanup_key(n),
                                         due_at=Now() + timedelta(seconds=delay))
    except IntegrityError:
        return False
    return True


def _number(claim) -> int:
    from workflow.models import PendingAction

    key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""
    try:
        return int(key.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


class ClearSessions:
    kind = CLEAR_SESSIONS
    redeliverable = True  # internal and idempotent: deletes rows that have already expired
    automated = True

    def lock_subject(self, claim) -> None:
        pass

    def record(self, claim, kind, data) -> None:
        """The chain survives a final failure: the next clean-up is queued anyway."""
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            schedule_session_cleanup(_number(claim) + 1, settings.CATALYST_SESSION_CLEANUP_SECONDS)

    def run(self, claim) -> None:
        from django.contrib.sessions.models import Session

        from workflow import ledger
        from workflow.models import PendingAction

        from accounts.models import LoginThrottle

        Session.objects.filter(expire_date__lt=timezone.now()).delete()
        # Throttle rows for usernames nobody has tried for a day, and that are not locked, would otherwise only grow.
        LoginThrottle.objects.filter(updated_at__lt=timezone.now() - timedelta(days=1)).exclude(
            locked_until__gt=timezone.now()).delete()
        n = _number(claim)
        ledger.finish(claim, self, status=PendingAction.Status.DONE,
                      write=lambda: schedule_session_cleanup(n + 1, settings.CATALYST_SESSION_CLEANUP_SECONDS))
