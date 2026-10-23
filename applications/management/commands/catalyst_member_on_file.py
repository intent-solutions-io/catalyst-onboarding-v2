"""Record that an invited member's first-generation agreement is on file (9kg.52; 030 Q4, D-51). Owner only.

Run as the migration owner: the application role may not insert the record (migration applications 0007), so no
model, web request or routine operator can set the flag. The row is the audit record (the agreement version as a
plain label, that completion was verified, who recorded it, when); a repeat for the same address supersedes the live
row. `--completion-verified` is required: without it nothing is recorded, because a member without a verified
completion is a new participant. A value that looks like a reference rather than a label is refused: no legacy
identifier and no document copy enter v2. Prints JSON without the address; the log line carries the recorder only.
Exit 0 recorded, 1 refused.
"""

import json
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from applications import members
from applications.forms import EMAIL_MAX
from applications.identity import email_key

logger = logging.getLogger("applications.members")


class Command(BaseCommand):
    help = "Record (or re-record) that a member's first-generation agreement is on file, by its version label."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--agreement-version", required=True,
                            help="the agreement version as a plain label (never an identifier, a link or a copy)")
        parser.add_argument("--completion-verified", action="store_true",
                            help="required: the owner verified the completion from the private roster")
        parser.add_argument("--recorded-by", required=True, help="who recorded this (recorded, never a secret)")
        parser.add_argument("--note", default="", help="a short reason, recorded on the row (no personal data beyond the address)")

    def handle(self, *args, email, agreement_version, completion_verified, recorded_by, note, **options):
        try:
            key = email_key(email)
        except ValueError:
            raise CommandError("not an email address") from None
        if len(key) > EMAIL_MAX:
            raise CommandError("the address is too long")
        if not completion_verified:
            raise CommandError("--completion-verified is required: a member without a verified completion is a new participant;"
                               " nothing was recorded")
        if not recorded_by.strip():
            raise CommandError("--recorded-by must name who recorded this")
        if len(recorded_by) > 200 or len(note) > 500:
            raise CommandError("--recorded-by is at most 200 characters and --note at most 500")
        try:
            members.check_label(agreement_version)
        except members.NotALabel as refused:
            raise CommandError(f"--agreement-version refused ({refused}): give the version as a plain label, never an"
                               " identifier, a link or a copy") from None
        try:
            row, superseded = members.record(email, agreement_version, recorded_by.strip(), note.strip())
        except DatabaseError as exc:  # the class only: a permission refusal names the table, never a value
            raise CommandError(f"the record could not be written ({type(exc).__name__}); run this as the migration owner") from None
        logger.warning("member on file recorded by %s%s", recorded_by.strip(), " (superseding the live record)" if superseded else "")
        self.stdout.write(json.dumps({"recorded": True, "agreement_version": row.agreement_version, "completion_verified": True,
                                      "recorded_at": row.recorded_at.isoformat(), "superseded": superseded}, sort_keys=True))
