from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Staff account (ADR-18, D-19). Applicants are dossier records, never users."""


class LoginThrottle(models.Model):
    """Password failures per username (6B.9, accounts.staff_access). `key` is a hash of the username: a failed
    attempt's text (often a mistyped password) is never stored."""

    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
