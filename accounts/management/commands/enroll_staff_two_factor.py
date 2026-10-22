"""Enrol a staff member's second factor (026 section 8, P6-D-3; 6B.9). Run by the owner, as the owner role.

Creates one TOTP device and one set of single-use recovery codes, replacing any the account had, and prints the
`otpauth://` URI and the codes once, to this terminal only: they are never logged or stored anywhere else. Hand
them to the staff member over the same private channel used for their password. Exit 0 done, 1 refused."""

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

RECOVERY_CODES = 10
logger = logging.getLogger("accounts.staff_access")


class Command(BaseCommand):
    help = "Enrol a staff member's TOTP device and recovery codes (owner only); prints them once."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, username, **options):
        user = get_user_model().objects.filter(username=username, is_staff=True, is_active=True).first()
        if user is None:
            raise CommandError("no active staff account with that username")
        replaced = TOTPDevice.objects.filter(user=user).exists() or StaticDevice.objects.filter(user=user).exists()
        with transaction.atomic():
            TOTPDevice.objects.filter(user=user).delete()
            StaticDevice.objects.filter(user=user).delete()
            totp = TOTPDevice.objects.create(user=user, name="authenticator", confirmed=True)
            static = StaticDevice.objects.create(user=user, name="recovery codes", confirmed=True)
            codes = [StaticToken.random_token() for _ in range(RECOVERY_CODES)]
            StaticToken.objects.bulk_create(StaticToken(device=static, token=code) for code in codes)
        logger.warning("two-factor enrolled for staff account %s%s", user.pk, " (replacing its devices)" if replaced else "")
        if replaced:
            self.stdout.write("note: this replaced the account's existing devices and recovery codes")
        self.stdout.write("Add this to the authenticator app (shown once):")
        self.stdout.write(totp.config_url)
        self.stdout.write("Recovery codes, each usable once (shown once):")
        for code in codes:
            self.stdout.write(f"  {code}")
