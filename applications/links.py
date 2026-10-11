"""Verification links (ADR-16, D-24): the challenge's random public id signed with a dedicated key.

The link is built from CATALYST_PUBLIC_BASE_URL, never from a request. Signing is deterministic, so a
permitted redelivery (D-20) carries the identical link under the same configuration. The signature only
makes the link unguessable; expiry, use and supersession are decided by the database alone when the link
is used (applications/confirmation.py, the view at CONFIRM_PATH). Never log, store in an event, or show staff the token or the link (D-24).
"""

from django.conf import settings
from django.core.signing import Signer

SALT = "catalyst.contact-verification"
CONFIRM_PATH = "/confirm/"


def signer() -> Signer:
    return Signer(key=settings.CATALYST_VERIFICATION_KEY, salt=SALT, fallback_keys=settings.CATALYST_VERIFICATION_FALLBACK_KEYS)


def verification_link(challenge_public_id) -> str:
    return f"{settings.CATALYST_PUBLIC_BASE_URL}{CONFIRM_PATH}{signer().sign(str(challenge_public_id))}/"
