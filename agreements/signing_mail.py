"""The service-sent signing link mail: the seam between the signing reminder (bead bgl.7) and provider distribution
(bead bgl.8, parity inventory 034 rows 27 and 28).

Today the only thing that puts the signing link in front of the applicant is Documenso's own distribution (P4-D-4,
P4-D-14; agreements.handlers.DistributeAgreement), and a second distribute of a PENDING envelope is NOT VERIFIED, so
the service has no path of its own that sends the link again. `resend_link` therefore reports `NOT_AVAILABLE`, and
the reminder records that the applicant was not reminded (one `signing_reminder_unavailable` staff item) instead of
pretending it was.

The contract bgl.8 fills, when the service sends the link mail itself:

- `resend_link` runs inside the caller's fenced transaction with the application and the instance locked, and writes
  database rows only: it freezes an `ApprovedMessage` of the signing-link kind from the owner-approved template (the
  link as a reproducible input, never stored in clear) and queues its send through correspondence.outbound, as every
  other kind is sent. It never calls Documenso or SMTP, so the reminder stays redeliverable.
- The reminder is the same link mail once more, in the thread of the first one: `Re: ` plus that mail's frozen subject,
  `In-Reply-To` and `References` its Message-ID (correspondence.messages.thread_headers, extended to the new kind).
- It returns the new message's `send_ref` as a string. The reminder handler has already checked the stage, the pause,
  the verified address, the hard bounce and quiet hours; the send handler re-checks them before the exchange.
"""

NOT_AVAILABLE = "no_service_signing_mail"


def available() -> bool:
    """Whether the service can send the signing link itself (bgl.8)."""
    return False


def resend_link(instance, *, actor_ref: str) -> str:
    """Queue one more copy of the signing link mail for `instance`; `NOT_AVAILABLE` while bgl.8 is not built."""
    return NOT_AVAILABLE
