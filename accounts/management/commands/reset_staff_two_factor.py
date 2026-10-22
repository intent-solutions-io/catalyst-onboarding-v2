"""Break-glass for a lost or compromised second factor (026 section 8, P6-D-3; 6B.9). Run by the owner.

Removes the account's devices and recovery codes, makes its password unusable and ends every session it has, so
nothing issued before the reset still works. Then the owner confirms who is asking (out of band, never by email
alone), sets a new password (`manage.py changepassword`) and enrols again (`manage.py enroll_staff_two_factor`).
Exit 0 done, 1 refused."""

import logging

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import LoginThrottle
from accounts.staff_access import throttle_key

logger = logging.getLogger("accounts.staff_access")


class Command(BaseCommand):
    help = "Remove a staff member's second factor, disable the password and end their sessions (owner only)."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, username, **options):
        User = get_user_model()
        user = User.objects.filter(username=username, is_staff=True).first()
        if user is None:
            raise CommandError("no staff account with that username")
        with transaction.atomic():
            devices = TOTPDevice.objects.filter(user=user).delete()[0] + StaticDevice.objects.filter(user=user).delete()[0]
            user.set_unusable_password()
            User.objects.filter(pk=user.pk).update(password=user.password)
            LoginThrottle.objects.filter(key=throttle_key(username)).delete()  # a lock-out must not outlast the reset
            ended = 0
            for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():  # a session names its user only inside its data
                if session.get_decoded().get("_auth_user_id") == str(user.pk):
                    session.delete()
                    ended += 1
        logger.warning("two-factor break-glass reset for staff account %s", user.pk)  # the record of each use
        self.stdout.write(f"removed {devices} two-factor records, disabled the password, ended {ended} sessions")
        self.stdout.write("next: confirm the person out of band, then changepassword and enroll_staff_two_factor")
