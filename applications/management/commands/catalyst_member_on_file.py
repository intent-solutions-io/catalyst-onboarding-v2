"""Record that an invited member's first-generation agreements are on file (9kg.52; 030 Q4, D-51). Owner only.

Run as the migration owner: the application role may not insert the record (migration applications 0008), so no
model, web request or routine operator can set it. Name each covered agreement type with its version as a plain
label (`--nda`, `--user-agreement`; at least one); `--completion-verified` is required, because a member without a
verified completion is a new participant and nothing is recorded. The address must already be known to v2 (an
invitation or an application): otherwise `unknown_member`. The same coverage again changes nothing ("unchanged");
different coverage is a correction and needs `--correct`, which supersedes the live record. A label or recorder
that is not a plain label (a link, a path, an address, a pasted identifier) is refused: no legacy identifier and no
document copy enter v2. Prints JSON without the address; the log line carries the recorder only. Exit 0 recorded or
unchanged, 1 refused.
"""

import json
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, IntegrityError

from applications import members
from applications.forms import EMAIL_MAX
from applications.identity import email_key

logger = logging.getLogger("applications.members")


class Command(BaseCommand):
    help = "Record (or correct) which first-generation agreements are on file for one member, by version label."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--nda", default=None, help="the NDA's version as a plain label, if covered")
        parser.add_argument("--user-agreement", default=None, help="the User Agreement's version as a plain label, if covered")
        parser.add_argument("--completion-verified", action="store_true",
                            help="required: the owner verified the completion off-system, from the private roster")
        parser.add_argument("--recorded-by", required=True,
                            help=f"who recorded this (a plain label, at most {members.RECORDER_MAX} characters)")
        parser.add_argument("--correct", action="store_true", help="replace a live record with different coverage")

    def handle(self, *args, email, nda, user_agreement, completion_verified, recorded_by, correct, **options):
        try:
            key = email_key(email)
        except ValueError:
            raise CommandError("refused (not_an_email_address)") from None
        if len(key) > EMAIL_MAX:
            raise CommandError("refused (address_too_long)")
        if not completion_verified:
            raise CommandError("refused (completion_not_verified): a member without a verified completion is a new"
                               " participant; nothing was recorded")
        try:
            row, outcome = members.record(email, {"nda": nda, "user_agreement": user_agreement}, recorded_by, correct=correct)
        except members.Refused as refused:
            raise CommandError(f"refused ({refused}); nothing was recorded") from None
        except IntegrityError:  # before DatabaseError: a concurrent run for the same address committed first
            raise CommandError("refused (concurrent_record): another run for this address committed first; run it again"
                               " to see the current record") from None
        except DatabaseError as exc:  # the class only: a permission refusal names the table, never a value
            raise CommandError(f"the record could not be written ({type(exc).__name__}); run this as the migration owner") from None
        if outcome != "unchanged":
            logger.warning("member on file %s by %s", outcome, row.recorded_by)
        self.stdout.write(json.dumps({"outcome": outcome, "covers": row.covers, "completion_verified": True,
                                      "recorded_at": row.recorded_at.isoformat()}, sort_keys=True))
