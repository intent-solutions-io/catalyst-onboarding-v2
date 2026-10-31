"""Bot checks on the public request form (034 row 4; bgl.2): a honeypot field and a signed render time.

Kept apart from `applications.forms.AccessRequestForm` so the applicant's field set and these checks change
independently. Both run after CSRF and the per-client limit, before the form is read, in the first generation's order:
the render time, then the honeypot.

- **Render time.** The page carries `form_token`, the render time signed with the site secret (django.core.signing,
  its own salt). A submission whose token is missing, forged, older than CATALYST_INTAKE_FORM_MAX_AGE_SECONDS or
  younger than CATALYST_INTAKE_FORM_MIN_AGE_SECONDS (a script posts faster than a person reads the page) gets the
  form back with its values and status 400; nothing is recorded. The token is stateless and so replayable inside its
  window: it proves a page was rendered recently, not first use; the per-client and per-address limits, CSRF and the
  duplicate rules bound a replay, and a single-use nonce would need server state per render.
- **Honeypot.** `website`, kept off screen and out of the accessibility tree, which a person never fills. A value
  there gets exactly the accepted response (the redirect to the received page) and nothing is recorded or sent.

The view logs a reason code only. CATALYST_INTAKE_FORM_CHECKS is on outside the test suite (config.guards).
"""

import time

from django.conf import settings
from django.core import signing

HONEYPOT_FIELD = "website"
TOKEN_FIELD = "form_token"
_SALT = "applications.abuse.request-access"
OK, MISSING, INVALID, EXPIRED, TOO_FAST = "ok", "missing", "invalid", "expired", "too_fast"


def enabled() -> bool:
    return settings.CATALYST_INTAKE_FORM_CHECKS is True


def issue_token(now: float | None = None) -> str:
    """The signed render time for one rendering of the form."""
    return signing.dumps({"t": int(now if now is not None else time.time())}, salt=_SALT, compress=False)


def check_token(token: str | None, now: float | None = None) -> str:
    """OK, or the reason code: MISSING, INVALID, EXPIRED or TOO_FAST."""
    if not token:
        return MISSING
    try:
        rendered = signing.loads(token, salt=_SALT)["t"]
    except (signing.BadSignature, KeyError, TypeError):
        return INVALID
    if not isinstance(rendered, int):
        return INVALID
    age = (now if now is not None else time.time()) - rendered
    if age > settings.CATALYST_INTAKE_FORM_MAX_AGE_SECONDS:
        return EXPIRED
    if age < settings.CATALYST_INTAKE_FORM_MIN_AGE_SECONDS:
        return TOO_FAST
    return OK


def honeypot_tripped(post) -> bool:
    return bool((post.get(HONEYPOT_FIELD) or "").strip())
