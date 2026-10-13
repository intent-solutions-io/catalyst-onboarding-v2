"""Bootstrap or recover the collected mailbox (016 B0, A-10; owner decision D-28). A host-level act: run by
whoever operates the host, outside the Django role matrix; the cursor records the start mode.

    manage.py correspondence_mailbox bootstrap --from-now     # earlier mail explicitly out of scope (recorded)
    manage.py correspondence_mailbox bootstrap --from-uid N
    manage.py correspondence_mailbox recover                  # walks from UID 1; never skips

Bootstrap refuses when the mailbox was collected before (that is recovery). Synthetic only (D-28)."""

import getpass
import logging

from django.core.management.base import BaseCommand, CommandError

from correspondence import inbound
from correspondence.imap import MailboxError


class Command(BaseCommand):
    help = "Bootstrap or recover the collected mailbox (016 B0)."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["bootstrap", "recover"])
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--from-now", action="store_true")
        group.add_argument("--from-uid", type=int)

    def handle(self, mode, from_now=False, from_uid=None, **options):
        try:
            if mode == "bootstrap":
                if not from_now and not from_uid:
                    raise CommandError("bootstrap needs --from-now or --from-uid N (an explicit start mode)")
                cursor = inbound.bootstrap_mailbox("from_now" if from_now else "from_uid", from_uid)
            else:
                cursor = inbound.recover_mailbox()
        except (inbound.Refused, MailboxError) as exc:
            raise CommandError(str(exc)) from None
        # B0: the record of who ran it. Events need an application, so the actor is logged (an operating-system
        # account name, not applicant data) and the cursor keeps the start mode (016 section 10.7).
        logging.getLogger("correspondence.mailbox").info(
            "mailbox %s by host user %s: cursor %s start_mode=%s", mode, getpass.getuser(), cursor.public_id, cursor.start_mode)
        self.stdout.write(f"cursor {cursor.public_id} state={cursor.state} start_mode={cursor.start_mode}")
