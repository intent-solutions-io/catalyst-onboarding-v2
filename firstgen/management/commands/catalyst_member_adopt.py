"""Attach existing first-generation members to v2 as active member cases (dy7.5; owner decision 211.7.6). Owner only.

    manage.py catalyst_member_adopt --input <private JSON file, or - for standard input> --recorded-by "<who>" [--dry-run]
                                    [--mailbox-domain <domain>]

Run as the migration owner, like `catalyst_import_v1` and `catalyst_member_on_file`: the application role may not
insert the member-on-file record, and the command refuses any other login. The input file is private and lives only
on the host (never in the repository): `{"members": [entry, ...]}`, one entry per person:

    {"email": "...", "display_name": "...",
     "user_agreement_envelope_id": "...", "user_agreement_version": "ua-v2.4",      (required)
     "nda_envelope_id": "...", "nda_version": "nda-v1.1",                          (optional; an NDA id needs its version)
     "mailbox_local_part": "..."}                                                  (optional: an existing company mailbox)

What each accepted entry creates, and every refusal, is in firstgen.adoption. A mailbox name is reserved on
`--mailbox-domain` (default CATALYST_PROVISIONING_DOMAIN). `--dry-run` runs everything in one transaction and rolls it
back, so it reports the same refusals a real run would. Prints JSON: counts, the outcome of each entry by its index
in the file, refusal codes and the public references of the applications; never an address, a name or an envelope
id. The input is never echoed, even when it cannot be read. The log line carries the recorder and the counts only.

Exit status: 0 every entry adopted or unchanged; 1 an entry was refused (the others are done; a re-run after fixing
the file adopts the rest and reports the done ones unchanged).
"""

import json
import logging
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from applications import members
from firstgen import adoption

logger = logging.getLogger("firstgen.adoption")


class _DryRun(Exception):
    pass


def _read(path: str) -> list:
    try:
        if path == "-":
            raw = sys.stdin.read()
        else:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read()
        document = json.loads(raw)
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:  # the class only: a message may quote the content
        raise CommandError(
            f"refused (input_unreadable): {type(exc).__name__}"
        ) from None
    if (
        not isinstance(document, dict)
        or set(document) != {"members"}
        or not isinstance(document["members"], list)
    ):
        raise CommandError(
            'refused (input_not_a_member_list): the file is {"members": [entry, ...]} and nothing else'
        )
    if not document["members"]:
        raise CommandError("refused (input_empty): the member list is empty")
    return document["members"]


class Command(BaseCommand):
    help = "Attach existing first-generation members (completed User Agreement, no v2 case) as active member cases."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            dest="input_path",
            required=True,
            help="the private JSON file on the host, or - for standard input",
        )
        parser.add_argument(
            "--recorded-by",
            required=True,
            help=f"who records this (a plain label, at most {members.RECORDER_MAX} characters)",
        )
        parser.add_argument(
            "--mailbox-domain",
            default=None,
            help="the domain of the existing mailboxes (default CATALYST_PROVISIONING_DOMAIN)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="do everything in one transaction, then roll back",
        )

    def handle(
        self, *args, input_path, recorded_by, mailbox_domain, dry_run, **options
    ):
        try:
            recorder = members.check_recorder(recorded_by)
        except members.Refused as why:
            raise CommandError(f"refused ({why})") from None
        domain = (
            mailbox_domain
            if mailbox_domain is not None
            else settings.CATALYST_PROVISIONING_DOMAIN or ""
        )
        domain = domain.strip().lower()
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            login = cursor.fetchone()[0]
        if login != settings.CATALYST_DB_ROLES["owner"]:
            raise CommandError(
                "refused (not_the_owner): run this as the migration owner"
            )
        entries = _read(input_path)
        if dry_run:  # one transaction around everything, rolled back; each entry is a savepoint inside it
            try:
                with transaction.atomic():
                    report = adoption.run(entries, recorder, domain)
                    raise _DryRun
            except _DryRun:
                pass
        else:  # one transaction per entry (firstgen.adoption.run)
            report = adoption.run(entries, recorder, domain)
        report = {"dry_run": dry_run, **report}
        self.stdout.write(json.dumps(report, indent=1, sort_keys=True))
        counts = report["counts"]
        logger.warning(
            "existing-member adoption %s by %s: %d adopted, %d unchanged, %d refused",
            "dry run" if dry_run else "run",
            recorder,
            counts["adopted"],
            counts["unchanged"],
            counts["refused"],
        )
        if counts["refused"]:
            raise CommandError(
                f"{counts['refused']} entr{'y' if counts['refused'] == 1 else 'ies'} refused: see the"
                " report",
                returncode=1,
            )
