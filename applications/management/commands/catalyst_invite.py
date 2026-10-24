"""Issue an invitation to apply while intake is invitation-only (9kg.43; 029 sections 4.1 and 7). Owner only.

Run as the migration owner: the application role may not insert an invitation (migration applications 0005), so no
model, web request or routine operator can issue one. The row is the audit record (who issued it, when, until when,
and which data notice the mail carried); a repeat for the same address supersedes the live invitation and issues a
new one. Prints JSON without the address: the invitation mail (subject and body, with the data notice rendered in
from the approved template, 9kg.52) for the owner to send by hand, and the notice's version and digest. A live
environment refuses to issue while the notice or the invitation wording is unapproved, synthetic or withdrawn
(applications.notices); a local or synthetic one prints the draft with its marker. `--format text` prints the mail
alone, ready to paste into a hand send, with the recorded digests after it. A concurrent run for the same address is
reported as such. The log line carries the issuer only. Exit 0 issued, 1 refused.
"""

import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, IntegrityError

from applications import invitations, notices
from applications.forms import EMAIL_MAX
from applications.identity import email_key

logger = logging.getLogger("applications.invitations")


class Command(BaseCommand):
    help = "Issue (or reissue) an invitation to apply for one address; --issued-by is recorded on the row."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--issued-by", required=True, help="who authorized this invitation (recorded, never a secret)")
        parser.add_argument("--days", type=int, default=None, help="lifetime in days (default: CATALYST_INVITATION_LIFETIME_SECONDS)")
        parser.add_argument("--note", default="", help="a short reason, recorded on the row (no personal data beyond the address)")
        parser.add_argument("--format", choices=("json", "text"), default="json",
                            help="json (the default) or text: the mail alone, for a hand send")

    def handle(self, *args, email, issued_by, days, note, format, **options):
        try:
            key = email_key(email)
        except ValueError:
            raise CommandError("not an email address") from None
        if len(key) > EMAIL_MAX:
            raise CommandError("the address is too long")
        if not issued_by.strip():
            raise CommandError("--issued-by must name who authorized the invitation")
        if len(issued_by) > 200 or len(note) > 500:
            raise CommandError("--issued-by is at most 200 characters and --note at most 500")
        lifetime = timedelta(days=days) if days is not None else timedelta(seconds=settings.CATALYST_INVITATION_LIFETIME_SECONDS)
        if lifetime <= timedelta(0):
            raise CommandError("the lifetime must be positive")
        try:
            mail = notices.invitation_mail()  # before any write: no invitation without the mail that carries the notice
        except notices.Unavailable as refused:
            raise CommandError(f"refused ({refused}): the owner approves the wording on the template screen first;"
                               " nothing was issued") from None
        try:
            invitation, superseded = invitations.issue(email, issued_by.strip(), lifetime, note.strip(), mail=mail)
        except IntegrityError:  # before DatabaseError: a concurrent run for the same address committed first
            raise CommandError("refused (concurrent_issue): another run for this address committed first; run it again"
                               " to supersede it") from None
        except DatabaseError as exc:  # the class only: a permission refusal names the table, never a value
            raise CommandError(f"the invitation could not be written ({type(exc).__name__}); run this as the migration owner") from None
        logger.warning("invitation issued by %s%s", issued_by.strip(), " (superseding the live one)" if superseded else "")
        if format == "text":
            self.stdout.write(f"Subject: {mail.subject}\n\n{mail.body}\n"
                              f"-- recorded: data notice version {mail.notice.version} ({mail.notice.sha256}),"
                              f" invitation wording {mail.template.sha256}{'; DRAFT, not approved' if mail.draft else ''}")
            return
        self.stdout.write(json.dumps({
            "issued": True, "expires_at": invitation.expires_at.isoformat(), "superseded": superseded,
            "mode": settings.CATALYST_INTAKE_MODE,
            "mail": {"subject": mail.subject, "body": mail.body, "draft": mail.draft,
                     "notice_version": mail.notice.version, "notice_sha256": mail.notice.sha256,
                     "template_version": mail.template.version, "template_sha256": mail.template.sha256},
        }, sort_keys=True))
