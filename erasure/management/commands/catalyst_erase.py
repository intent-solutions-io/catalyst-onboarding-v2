"""Erase one person under POL-10 (9kg.32; 029 section 6.2): run by the owner with the retention role's login, never
by a web or worker process and never from a screen.

    manage.py catalyst_erase --subject <public reference> --authority <code> --reason <code>
    manage.py catalyst_erase --subject <public reference> --handoff <provider> --completed-on YYYY-MM-DD

The subject is an application's public reference (or an invitation's, for a person who never applied); the erasure
covers every record of that person's email key. It refuses while the registry (erasure.registry) has an undecided
value. Re-run the same command after any interruption: an open intent is finished; a completed erasure is left alone.

Prints one JSON line: the outcome, the number of values changed, the provider handoffs owed and the journal head.
Keep the head out of band (the private operations record): `catalyst_erasure_record --expect-head` checks it. Never
prints an address, a name or a numeric id. Exit 0 on success, 1 when refused."""

import json
import uuid

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand

from config import runtime
from erasure import record, service


class Command(BaseCommand):
    help = "Erase one person (retention role only), or record a completed provider handoff."

    def add_arguments(self, parser):
        parser.add_argument("--subject", required=True, help="the application's (or invitation's) public reference")
        parser.add_argument("--authority", default="", help="the authority for the erasure, as a code")
        parser.add_argument("--reason", default="", help="the reason, as a code")
        parser.add_argument("--handoff", default="", choices=("", *record.HANDOFFS), help="a provider deletion done")
        parser.add_argument("--completed-on", default="", help="the date the provider deletion was completed")

    def refuse(self, code, detail=()):
        self.stderr.write(f"erasure refused: {code}" + (f" ({', '.join(detail)})" if detail else ""))
        raise SystemExit(1)

    def handle(self, *args, subject, authority, reason, handoff, completed_on, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            self.refuse("not_a_management_process")
        try:
            subject = str(uuid.UUID(subject))
        except ValueError:
            self.refuse("malformed_request")
        if handoff:
            try:
                head = service.handoff(subject, handoff, completed_on)
            except service.Refused as exc:
                self.refuse(exc.code)
            self.stdout.write(json.dumps({"status": "handoff_recorded", "subject": subject, "provider": handoff,
                                          "journal_head": head}, sort_keys=True))
            return
        db = settings.DATABASES["default"]
        try:
            with psycopg.connect(host=db["HOST"], port=db.get("PORT") or "5432", dbname=db["NAME"], user=db["USER"],
                                 password=db["PASSWORD"]) as conn:
                outcome = service.erase(conn, subject, authority, reason)
        except service.Refused as exc:
            self.refuse(exc.code, exc.detail)
        except psycopg.Error as exc:  # its detail can quote a row: only the class and the code
            self.refuse(f"database_error {type(exc).__name__} {exc.sqlstate or ''}".rstrip())
        self.stdout.write(json.dumps({"status": outcome.status, "subject": outcome.subject_ref, "changed": outcome.changed,
                                      "handoffs": outcome.handoffs, "resumed": outcome.resumed,
                                      "journal_head": outcome.journal_head}, sort_keys=True))
