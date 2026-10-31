"""Set where collection starts in the mailbox v2 takes over at the swap (bgl.6; 034 section 3.2). A host-level act, like
`correspondence_mailbox`: run by whoever operates the host, after the first generation's poll is stopped and before the
deploy that sets CATALYST_MAIL_TAKEOVER.

    manage.py catalyst_mail_cursor_start --from-uid N --uidvalidity V [--override]

N is the first UID v2 reads: the first generation's cursor's last UID plus one. V is that cursor's UIDVALIDITY. Nothing
connects to the mailbox (the login that reaches it is refused until the takeover deploy); the first pass checks V and
blocks instead of reprocessing the inbox when it differs. Refused when the cursor is already set or mail was already
collected, unless --override, which moves the existing cursor (a new epoch). Messages below N are out of scope, and a
staff item records that."""

import getpass
import logging
import os

from django.core.management.base import BaseCommand, CommandError

from correspondence import inbound


def host_user() -> str:
    """The operating-system account that ran the command; a container user with no passwd entry is named by its uid
    (getpass raises there, and the record must not cost the act)."""
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return f"uid {os.getuid()}"


class Command(BaseCommand):
    help = "Set the collected mailbox's cursor at a named UIDVALIDITY and UID (the mailbox takeover, bgl.6)."

    def add_arguments(self, parser):
        parser.add_argument("--from-uid", type=int, required=True, help="the first UID to read (the old cursor's last UID + 1)")
        parser.add_argument("--uidvalidity", type=int, required=True, help="the mailbox folder's UIDVALIDITY")
        parser.add_argument("--override", action="store_true", help="move a cursor that is already set")

    def handle(self, from_uid, uidvalidity, override=False, **options):
        try:
            cursor = inbound.start_cursor(from_uid, uidvalidity, override=override)
        except inbound.Refused as exc:
            raise CommandError(str(exc)) from None
        # The record of who ran it: an operating-system account name, never applicant data (016 section 10.7).
        logging.getLogger("correspondence.mailbox").info(
            "mailbox cursor start by host user %s: cursor %s uidvalidity=%s from_uid=%s override=%s epoch=%s",
            host_user(), cursor.public_id, cursor.uidvalidity, cursor.last_uid + 1, override, cursor.epoch)
        self.stdout.write(f"cursor {cursor.public_id} start_mode={cursor.start_mode} uidvalidity={cursor.uidvalidity} "
                          f"from_uid={cursor.last_uid + 1} epoch={cursor.epoch}")
