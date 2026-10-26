"""The public references held for one address, to name a person to `catalyst_erase` (9kg.72): the owner types the
address the erasure request came from; the command prints the application references and invitation references whose
email key is that address's, never the address itself.

    manage.py catalyst_erasure_subjects <address>

Read-only, owner-run (the migration owner's or the retention role's login), never in a web or worker process. A person
invited who never applied has only an invitation reference; `catalyst_erase --subject <reference>` takes either kind
and covers every record of that email key. Prints one JSON line. Exit 0 found, 1 when nothing is held for the address
(already erased, or never known) or refused."""

import json

from django.core.management.base import BaseCommand, CommandError

from applications.identity import email_key
from applications.models import Application, Invitation
from config import runtime


class Command(BaseCommand):
    help = "Print the application and invitation references held for one address (for catalyst_erase)."

    def add_arguments(self, parser):
        parser.add_argument("address")

    def handle(self, *args, address, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            raise CommandError("refused (not_a_management_process)")
        try:
            key = email_key(address)
        except ValueError:
            raise CommandError("not an email address") from None
        found = {
            "applications": sorted(str(r) for r in Application.objects.filter(email_key=key).values_list("public_ref", flat=True)),
            "invitations": sorted(str(r) for r in Invitation.objects.filter(email_key=key).values_list("public_id", flat=True)),
        }
        self.stdout.write(json.dumps(found, sort_keys=True))
        if not (found["applications"] or found["invitations"]):
            raise SystemExit(1)
