"""Who is due for erasure under the decided retention clocks, for the owner's monthly procedure (9kg.75; 031 section
2.5; the clocks of 033 Q1, `erasure.registry.CLOCK_DAYS`).

    manage.py catalyst_retention_due [--as-of YYYY-MM-DD]

Read-only and listing only: it erases nothing (that stays `catalyst_erase`, one owner act per person). Runs only as the
retention role's login, never in a web or worker process, like `catalyst_erasure_subjects`. The output is one JSON
line of public references and counts, never an address or a name.

- **R1**: every application of the person is terminal (declined, withdrawn or closed), no agreement was issued to them
  and no first-generation agreement is on file; due once the latest terminal event is older than R1.
- **R2**: invited, never applied (no application for the address); due once the newest invitation expired more than
  R2 ago. Named by the invitation's reference (9kg.72).
- **R3** (agreements issued or on file): counted, not computable: the period is counsel's and the engagement end is
  not yet recorded.
- **R4** (a request from the person): not computable here; the service does not receive the requests.
- A person with an open application is never due (the erasure itself refuses until every application is terminal);
  they are counted as `open`. Already-erased people are left out.

Refuses while the registry is undecided (there is no clock to apply). Prints whether the values are provisional.
Exit 0.
"""

import json
from datetime import date, datetime, time, timedelta, timezone

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config import runtime
from erasure import registry, service

TERMINAL = ("declined", "withdrawn", "closed")

PEOPLE = """
WITH apps AS (
  SELECT a.id, a.public_ref, a.email_key, a.stage,
         coalesce((SELECT max(e.occurred_at) FROM applications_applicationevent e
                   WHERE e.application_id = a.id AND e.data->>'to' = a.stage), a.updated_at) AS ended
    FROM applications_application a
   WHERE a.email_key NOT LIKE 'erased:%%')
SELECT (array_agg(public_ref ORDER BY ended DESC, id DESC))[1] AS ref,
       bool_and(stage = ANY(%(terminal)s)) AS terminal,
       max(ended) AS ended,
       bool_or(EXISTS (SELECT 1 FROM agreements_agreementinstance i WHERE i.application_id = apps.id))
         OR EXISTS (SELECT 1 FROM applications_memberagreementonfile m WHERE m.email_key = apps.email_key) AS agreements
  FROM apps GROUP BY email_key
"""

NEVER_APPLIED = """
SELECT (array_agg(i.public_id ORDER BY i.issued_at DESC, i.id DESC))[1] AS ref, max(i.expires_at) AS expired
  FROM applications_invitation i
 WHERE i.email_key NOT LIKE 'erased:%%'
   AND NOT EXISTS (SELECT 1 FROM applications_application a WHERE a.email_key = i.email_key)
 GROUP BY i.email_key
HAVING bool_and(i.used_at IS NULL)
"""


def due(conn, now: datetime) -> dict:
    r1 = now - timedelta(days=registry.CLOCK_DAYS["R1"])
    r2 = now - timedelta(days=registry.CLOCK_DAYS["R2"])
    out = {"R1": [], "R2": [], "R3_counted": 0, "open": 0}
    for ref, terminal, ended, agreements in conn.execute(PEOPLE, {"terminal": list(TERMINAL)}):
        if not terminal:
            out["open"] += 1
        elif agreements:
            out["R3_counted"] += 1
        elif ended <= r1:
            out["R1"].append(str(ref))
    for ref, expired in conn.execute(NEVER_APPLIED):
        if expired <= r2:
            out["R2"].append(str(ref))
    return out


class Command(BaseCommand):
    help = "List, by public reference only, the people due for erasure under the retention clocks (retention login)."

    def add_arguments(self, parser):
        parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                            help="evaluate the clocks at the start of this UTC day (default: now)")

    def handle(self, *args, as_of, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            raise CommandError("refused (not_a_management_process)")
        if registry.problems():
            raise CommandError("refused (registry_undecided): there is no clock to apply")
        now = datetime.combine(as_of, time(), timezone.utc) if as_of else datetime.now(timezone.utc)
        db = settings.DATABASES["default"]
        try:
            with psycopg.connect(host=db["HOST"], port=db.get("PORT") or "5432", dbname=db["NAME"], user=db["USER"],
                                 password=db["PASSWORD"]) as conn:
                conn.read_only = True  # before the first statement opens a transaction
                service._role_check(conn)
                found = due(conn, now)
        except service.Refused as exc:
            raise CommandError(f"refused ({exc.code})") from None
        except psycopg.Error as exc:  # the class and code only: a detail can quote a row
            raise CommandError(f"refused (database_error {type(exc).__name__})") from None
        found["R1"].sort()
        found["R2"].sort()
        self.stdout.write(json.dumps({
            "as_of": now.isoformat(), "provisional": registry.PROVISIONAL, "clock_days": registry.CLOCK_DAYS,
            "due": {"R1": found["R1"], "R2": found["R2"]},
            "counts": {"R1": len(found["R1"]), "R2": len(found["R2"]), "R3_not_computable": found["R3_counted"],
                       "open": found["open"]},
            "not_computable": {"R3": "engagement_end_not_recorded_and_period_is_counsels",
                               "R4": "requests_are_not_received_by_the_service"},
        }, sort_keys=True))
