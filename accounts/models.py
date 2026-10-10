from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Staff account (ADR-18, D-19). Applicants are dossier records, never users."""
