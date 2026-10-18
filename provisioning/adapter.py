"""The one narrow interface to the mail host (023 sections 3, 11.1 and 11.8; P5-D-4).

Only the documented mailbox operations Catalyst needs exist here: read one mailbox, create one. There is no delete,
no suspend, no domain or reseller operation, and no way to name a path. Synthetic P5 uses a local fake that implements
this interface in process (`CATALYST_PROVISIONING_ADAPTER`, test only). A live adapter does not exist: building one,
its key (for one hosting user, never a reseller key) and the separate credential service it runs in are pre-live
gates (P5-D-6, D-47).

Errors follow the P4 taxonomy: only a 4xx other than 429 is definite; a 5xx (including MXroute's 500 for a failed or
ambiguous lookup), a timeout after sending, or anything else is an unknown outcome.
"""

import re
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string


CODE = re.compile(r"[a-z0-9_]{1,40}")


class AdapterError(Exception):
    """`code` is a reason code; `sent` says whether the request may have reached the host."""

    def __init__(self, code: str, *, sent: bool, status: int | None = None, retry_after: float | None = None):
        # A reason code only: anything else (a response body, an address) is replaced, so it can never reach a
        # record, an event or a log (security review of PR #53).
        code = str(code or "").lower()
        code = code if CODE.fullmatch(code) else "adapter_error"
        super().__init__(code)
        self.code, self.sent, self.status, self.retry_after = code, sent, status, retry_after

    @property
    def unknown(self) -> bool:
        """For a write: the host may have acted. A 429 after sending is unknown too: a gateway can throttle after the
        create landed, so only a read decides (never a rejection that frees the address)."""
        if not self.sent:
            return False
        if self.status is None or self.status == 429:
            return True
        return not (400 <= self.status < 500)

    @property
    def conflict(self) -> bool:
        return self.status == 409 or self.code == "conflict"

    def __repr__(self):
        return f"AdapterError({self.code!r}, sent={self.sent}, status={self.status})"


@dataclass(frozen=True)
class Mailbox:
    """The allowlisted facts of one mailbox read. Never a password."""

    local_part: str
    domain: str
    quota_mb: int
    send_limit: int
    suspended: bool

    def facts(self) -> dict:
        return {"local_part": self.local_part, "domain": self.domain, "quota_mb": self.quota_mb,
                "send_limit": self.send_limit, "suspended": self.suspended}


class MailHost:
    """The interface. `read` returns None only on an authoritative "not found"; anything uncertain raises."""

    def read(self, domain: str, local_part: str) -> Mailbox | None:
        raise NotImplementedError

    def create(self, domain: str, local_part: str, password: str, quota_mb: int, send_limit: int) -> None:
        raise NotImplementedError


def host() -> MailHost:
    path = settings.CATALYST_PROVISIONING_ADAPTER
    if not path:
        raise AdapterError("no_adapter_configured", sent=False)
    return import_string(path)()
