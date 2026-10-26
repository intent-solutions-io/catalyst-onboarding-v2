"""The public references held for one address, to name a person to `catalyst_erase` (9kg.72): the owner types the
address the erasure request came from; the command prints the application references and invitation references whose
email key is that address's, never the address itself.

    manage.py catalyst_erasure_subjects <address>

Read-only, and only where the erasure itself runs: the retention role's login and nothing else (erasure.service's
role check), never in a web or worker process, so the lookup is not an "is this address known?" oracle for any other
login (security review of PR #107). A person invited who never applied has only an invitation reference;
`catalyst_erase --subject <reference>` takes either kind and covers every record of that email key. A first-generation
member record with no application or invitation is counted (`member_on_file`) but has no reference to name. The address
is a bare address: a display-name form (`Name <a@b>`) or one over the intake's length bound is refused.

Prints one JSON line. Exit 0 when a reference was found, 3 when nothing nameable is held (already erased, or never
known), 1 when refused."""

import json

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from applications.forms import EMAIL_MAX
from applications.identity import email_key
from config import runtime
from erasure import service


class Command(BaseCommand):
    help = "Print the application and invitation references held for one address (retention login; for catalyst_erase)."

    def add_arguments(self, parser):
        parser.add_argument("address")

    def handle(self, *args, address, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            raise CommandError("refused (not_a_management_process)")
        if len(address) > EMAIL_MAX or any(c in address for c in "<> \t"):
            raise CommandError("a bare address is required")
        try:
            key = email_key(address)
        except ValueError:
            raise CommandError("not an email address") from None
        db = settings.DATABASES["default"]
        try:
            with psycopg.connect(host=db["HOST"], port=db.get("PORT") or "5432", dbname=db["NAME"], user=db["USER"],
                                 password=db["PASSWORD"]) as conn:
                service._role_check(conn)
                found = {
                    "applications": sorted(str(r) for (r,) in conn.execute(
                        "SELECT public_ref FROM applications_application WHERE email_key = %s", [key])),
                    "invitations": sorted(str(r) for (r,) in conn.execute(
                        "SELECT public_id FROM applications_invitation WHERE email_key = %s", [key])),
                    "member_on_file": conn.execute(
                        "SELECT count(*) FROM applications_memberagreementonfile WHERE email_key = %s", [key]).fetchone()[0],
                }
        except service.Refused as exc:
            raise CommandError(f"refused ({exc.code})") from None
        except psycopg.Error as exc:  # the class and code only: a detail can quote a row
            raise CommandError(f"refused (database_error {type(exc).__name__})") from None
        self.stdout.write(json.dumps(found, sort_keys=True))
        if not (found["applications"] or found["invitations"]):
            raise SystemExit(3)
