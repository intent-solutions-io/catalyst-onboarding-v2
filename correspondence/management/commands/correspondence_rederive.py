"""Re-derive stored inbound text after a derivation or redaction version bump (016 3.5; owner decision D-28).

For each message derived under an older version: re-read the source from its mailbox location (read-only)
and replace the derivative. When the source is no longer at that location (another UIDVALIDITY, or gone), the
new redaction is applied to the stored derivative itself and that is recorded in `omitted_parts`. The old
text is never kept: it may hold the very secret the bump exists to remove. Synthetic only."""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.conf import settings

from correspondence import mime
from correspondence.imap import MailboxClient, MailboxError
from correspondence.models import InboundMessage
from correspondence.staff_items import event


class Command(BaseCommand):
    help = "Re-derive inbound message text after a derivation or redaction version bump (016 3.5)."

    def handle(self, *args, **options):
        stale = InboundMessage.objects.filter(
            Q(redaction_version__lt=mime.REDACTION_VERSION) | Q(derivation_version__lt=mime.DERIVATION_VERSION)
        ).select_related("application").order_by("id")
        done = from_source = 0
        client = None
        try:
            try:
                client = MailboxClient(timeout=settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS)
            except MailboxError:
                client = None
            validities = {}
            for message in stale:
                location = message.locations.order_by("-id").first()
                raw = None
                if client is not None and location is not None and message.original_sha256:
                    try:
                        if location.folder not in validities:
                            validities[location.folder] = client.examine(location.folder)[0]
                        if validities[location.folder] == location.uidvalidity:
                            data = client.fetch(location.uid)
                            raw = data if mime.digest(data) == message.original_sha256 else None
                    except MailboxError:
                        raw = None
                with transaction.atomic():
                    if raw is not None:
                        derived = mime.derive(raw, max_text_chars=settings.CATALYST_MAIL_MAX_TEXT_CHARS)
                        text, omitted, redactions = derived.text, derived.omitted_parts, derived.redactions
                        from_source += 1
                    else:
                        text, count = mime.redact(message.derived_text)
                        omitted = [*message.omitted_parts, {"part": "derivative", "reason": "rederived_from_derivative"}]
                        redactions = {**message.redactions, "confirmation_link": message.redactions.get("confirmation_link", 0) + count}
                    InboundMessage.objects.filter(pk=message.pk).update(
                        derived_text=text, omitted_parts=omitted, redactions=redactions,
                        derivation_version=mime.DERIVATION_VERSION, redaction_version=mime.REDACTION_VERSION)
                    event(message.application, "inbound_rederived", {
                        "message": str(message.public_id), "from_source": raw is not None,
                        "old_versions": [message.derivation_version, message.redaction_version],
                        "new_versions": [mime.DERIVATION_VERSION, mime.REDACTION_VERSION],
                        "old_text_sha256": mime.digest(message.derived_text.encode()),
                        "new_text_sha256": mime.digest(text.encode())})
                done += 1
        finally:
            if client is not None:
                client.close()
        self.stdout.write(f"re-derived {done} messages ({from_source} from the mailbox)")
