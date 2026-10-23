from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Now


class User(AbstractUser):
    """Staff account (ADR-18, D-19). Applicants are dossier records, never users."""


class LoginThrottle(models.Model):
    """Password failures per username (6B.9, accounts.staff_access). `key` is a hash of the username: a failed
    attempt's text (often a mistyped password) is never stored."""

    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class RequestThrottle(models.Model):
    """One bucket of the public-endpoint limits (9kg.29, config.throttle). `key` is sha256(scope:value): never a client
    address, an address key or a token. `count` is the requests admitted in the fixed window that began at
    `window_start`, both judged by the database clock. Rows untouched for a day are swept with the sessions."""

    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=1)
    window_start = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())
