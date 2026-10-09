# S1-T1 Compatibility and Comparison Evidence (handoff 1A)

| Field | Value |
|---|---|
| Document | `012-RA-ANLY-s1-t1-compatibility-evidence` |
| Version | 0.1.0 |
| Status | **EVIDENCE FOR OWNER DECISIONS.** Recommendations only. ADR-03, ADR-14, ADR-17 and ADR-18 stay **PENDING OWNER DECISION** (bead S1-D). Nothing here is application code, a migration, or approval to start 1B. |
| Owner | Jeremy Longshore |
| Date | 2026-10-09 |
| Bead | S1-T1, "Select and verify the Django, Python, PostgreSQL, driver and job-runner versions for the first slice" |
| Brief | `005` S1.6a; contract approval `011` section 10 |
| Classification | Public; synthetic data and a throwaway test password only; no provider keys read; no production contact |

> **Status: PRELIMINARY, subject to review.** The 22 `TEST-S1-` cases remain **NOT RUN**. The proofs
> below are throwaway compatibility checks, run in a disposable environment outside this repository.

## 1. How the evidence was produced

- **Environment:** the session's private scratch directory, outside the repository. One uniquely named
  PostgreSQL container on loopback with tmpfs storage, recreated from scratch by each run. Two virtual
  environments local to that directory (no global install). Synthetic `example.test` data only.
- **Interpreters:** Python 3.12.3 (system) and Python 3.14.0 (a scratch-local install; `uv` 0.9.8's
  catalogue did not offer 3.14.8, the current patch). Both produced identical results.
- **Packages:** Django 5.2.18, psycopg 3.3.6 (binary), Procrastinate 3.10.0 with its Django extra;
  PostgreSQL 16.15 (`postgres:16` image).
- **Evidence labels:** **DOCUMENTED** means an official source states it; **DEMONSTRATED** means the
  proof below ran and showed it with these versions; **INSPECTED** means read in installed source code;
  **ASSESSED** means a judgement from the facts, not a measurement.
- **Reproduce:** recreate the files in appendix A in one directory, create a virtual environment with the
  three packages above, then run `bash run_all.sh <venv>/bin/python`. Each run removes and recreates only
  the container named `s1t1-pg-disposable`.

## 2. Results (both interpreters, from a fresh database)

| # | Proof | Result |
|---|---|---|
| 1 | Atomic enqueue: application insert plus job insert; rollback leaves neither; commit makes both visible to a **separate** connection | **PASS** for all three paths: Procrastinate through Django's own connection (`transaction.atomic`), the custom ledger (ORM row), and Procrastinate's documented external psycopg connection (`configure(connection=...)`) |
| 2a | Procrastinate worker killed with SIGKILL mid-job | job stays `doing`; **no automatic recovery** after 12 s; recovered only when the application calls `get_stalled_jobs()` and `retry_job()`; a fresh worker then completed it |
| 2b | Custom-ledger worker killed with SIGKILL mid-action | row stays `running` under its lease; a second worker cannot claim it while the lease is live; after expiry (database clock) it is reclaimed with attempts counted; the stale worker's late write updates **0 rows**; the current worker's fenced write updates 1; a row at its attempt limit becomes `failed` without running; a duplicate idempotency key is refused |
| 3 | Append-only history (trigger plus role separation) | the application role can append; ORM `update()`, ORM `delete()`, raw `UPDATE`, `TRUNCATE` (no privilege) and disabling the trigger (not owner) are all refused; setting the retention flag does not help a non-member; the retention role deletes only with a stated reason, and each delete writes an audit row; nobody can `UPDATE`; the schema owner is blocked from `TRUNCATE` by the trigger but **can disable the trigger** |
| 4 | Minimal custom user before the first migration | `accounts.0001_initial` (custom `AbstractUser`) applies before `admin.0001_initial`; the applicant `Application` model has no foreign key to the user model |

Full raw output: appendix B.

## 3. Decision table (for the owner; nothing chosen here)

| ADR | Recommendation | Evidence | Alternatives | Limitations | What the owner approves |
|---|---|---|---|---|---|
| ADR-03 job mechanism | **Custom domain ledger** (the `005` S1.4 rules) as the single source of truth for pending work, run by a management-command worker. | Proofs 1 and 2b; section 4 comparison | Procrastinate 3.10.0 as the runner, with a domain table for pause, `uncertain` and staff state (proofs 1 and 2a) | We own and test the worker loop: backoff, signals, logging, a dead-worker monitor. A lease fence protects database writes only. It cannot stop a slow worker that already sent an email from sending it (section 4) | the mechanism; that S1-T5 builds the ledger; whether to revisit if periodic scheduling or LISTEN/NOTIFY wake-ups become necessary |
| ADR-14 append-only | **Database trigger plus role separation:** the web and worker connect as a non-owner role; a separate retention role may delete only with a stated reason, audited by the trigger; no role may update history; migrations alone run as the schema owner. | Proof 3 | ORM-level guards only, which proof 3 shows cannot stop raw SQL or `QuerySet.update()`; an architecture test (TEST-S1-21 fallback) | The schema owner can disable the trigger, so the guarantee depends on never running the application as the owner and on reviewing migrations. Retention here means deleting a row. If POL-10 later requires redaction instead, the retention path needs a second, separately audited operation | the trigger form and the three-role model; that retention deletes, rather than redacts, are the default until POL-10 decides |
| ADR-17 versions | **Django 5.2.18 (LTS), Python 3.14 (latest patch, 3.14.8 at the time of writing), PostgreSQL 16.15, psycopg 3.3.6, pytest 9.1.1, pytest-django 4.14.0**; Procrastinate 3.10.0 only if ADR-03 chooses it. | Section 5; proofs ran on 3.14.0 and 3.12.3 | Python 3.12 (security-only until 2028-10; the default system interpreter); Django 6.1.2 (not LTS; extended support ends 2027-12); PostgreSQL 17 or 18 (longer support) | The proofs ran on 3.14.0, not 3.14.8, and pytest and pytest-django were not run. Both are only DOCUMENTED. The production host's PostgreSQL version was not checked (out of this handoff's authority) | exact versions; Python 3.14 over 3.12; PostgreSQL 16 confirmed or changed once the host version is known |
| ADR-18 user model | **Minimal `accounts.User(AbstractUser)`** with no extra fields, set as `AUTH_USER_MODEL` before the first migration. Users are staff only; applicants are dossier records with no foreign key to users. | Proof 4; Django 5.2 docs | Django's default `User` (changing it later "can be complex", per the docs); a custom authentication system (out of scope) | MFA package fields, if any, are added later by normal migrations. Nothing is gained by delaying the swap | the model and its place in the first migration |

## 4. ADR-03 comparison against the required behaviour

| Required behaviour | Custom domain ledger | Procrastinate 3.10.0 |
|---|---|---|
| Enqueue in the same transaction as the domain write | DEMONSTRATED (proof 1) | DEMONSTRATED through Django's connection and through the documented external psycopg connection (proof 1). The Django connector runs SQL on `connections[alias]` (INSPECTED); the external-connection page lists only `SyncPsycopgConnector`, `PsycopgConnector` and `SQLAlchemyPsycopg2Connector` (DOCUMENTED) |
| Worker-death recovery | DEMONSTRATED automatic once the lease expires: the claim query takes expired rows; attempts are counted at claim | DEMONSTRATED but **not automatic**: needs an application-scheduled `get_stalled_jobs()` + `retry_job()` (for example a periodic task); detection is based on worker heartbeats (INSPECTED) |
| Late writer after reclaim | DEMONSTRATED: fenced write updates 0 rows | not demonstrated; job status updates are Procrastinate's own |
| `uncertain` external outcomes and reconciliation | ASSESSED: an explicit status in the domain model (designed, not demonstrated); reconciliation is domain code either way | ASSESSED: no `uncertain` job status (statuses INSPECTED: todo, doing, succeeded, failed, cancelled, aborting, aborted); the domain still needs its own state; retries re-run the task, so tasks must be idempotent |
| Duplicate protection | DEMONSTRATED: unique idempotency key | DOCUMENTED and INSPECTED: `queueing_lock` and `lock` on jobs; not demonstrated. Its docs warn that a lock violation inside the caller's transaction aborts that transaction unless a savepoint isolates it |
| Per-subject pause that still lets staff messages run | ASSESSED: designed into the claim (`005` S1.4 rules 1 and 8), not demonstrated | ASSESSED: no per-subject pause in the job model; it needs a domain gate checked by every task, or cancelling and re-deferring jobs |
| Staff visibility | ASSESSED: the ledger is a domain model, so read-only admin works as for any model | INSPECTED: a bundled read-only Django admin for jobs (`has_add/change/delete_permission` return false) |
| Maintenance burden | DEMONSTRATED core is about 30 lines (`ledger_worker.py`); ASSESSED: a production worker with backoff, signals and logging is a few hundred lines plus tests, all owned by us | 8 extra packages installed (`asgiref`, `attrs`, `croniter`, `psycopg-pool`, `python-dateutil`, `six`, `packaging`, `typing-extensions`); 4 tables and 18 database functions under its own migrations; releases every one to three months in 2026 (3.7.0 to 3.10.0); its Django docs say it is tested against the latest Django for each Python, so Django 5.2 on Python 3.12+ is not in its stated test matrix (DOCUMENTED) |
| Useful extras | none | built-in periodic (cron) tasks, LISTEN/NOTIFY wake-ups, mature async worker |

**Why the recommendation is the custom ledger (ASSESSED, for the owner to weigh).** Procrastinate's
transactional enqueue works with our versions, so that is no longer a reason to reject it. Pause, the
`uncertain` state, staff state and reconciliation still need a domain table with Procrastinate. Its
dead-worker recovery also needs scheduled application code. Together that means two sources of truth for
pending work and more dependencies, in exchange for scheduling and wake-ups the first slice does not use.
If later phases need cron-like schedules or low-latency wake-ups, revisit this with that evidence.

**A database fence is not an effect fence.** Proof 2b shows the late worker's *database* write is
refused. It does not show, and cannot show, that the late worker did not already call the provider.
External effects stay at-least-once unless the provider offers an idempotency key or the domain marks
the outcome `uncertain` and reconciles before retrying (ADR-15).

## 5. Versions and support statements (sources read 2026-10-09)

| Component | Proposed | Support statement | Source |
|---|---|---|---|
| Django | 5.2.18 | 5.2 LTS: latest release 5.2.18; extended support until April 2028. Next LTS is 6.2 (April 2027) | djangoproject.com "Download" (supported versions table) |
| Django and Python | Python 3.10 to 3.14 | "Django 5.2 supports Python 3.10, 3.11, 3.12, 3.13, and 3.14 (as of 5.2.8)" | Django 5.2 release notes, "Python compatibility" |
| Django and PostgreSQL | 14 and later | "Django 5.2 supports PostgreSQL 14 and higher" | Django 5.2 release notes |
| Python | 3.14.x (3.14.8 current) | 3.14 bugfix until 2030-10; 3.13 security until 2029-10; 3.12 security until 2028-10 (latest 3.12.15) | python.org "Downloads" release status table |
| PostgreSQL | 16.15 | 16: current minor 16.15, final release November 9, 2028; 17.11 until 2029; 18.6 until 2030 | postgresql.org "Versioning policy" |
| psycopg | 3.3.6 | latest on PyPI (2026-09-18); Python 3.10 and later; Django requires psycopg 3.1.8 or later (Django databases notes, reported by the architect review; INSPECTED) | PyPI |
| pytest | 9.1.1 | Python 3.12 to 3.14 classifiers | PyPI |
| pytest-django | 4.14.0 | declares Django 5.2 and 6.0, Python 3.12 to 3.14 | PyPI classifiers |
| Procrastinate | 3.10.0 (only if chosen) | Python 3.10 and later; `django>=2.2` extra; no explicit Django 5.2 test statement | PyPI; Procrastinate Django docs |

Nothing was copied from an older worktree; every version comes from these sources.

## 6. What 1A did not do

No application code, project skeleton or migration in this repository; no 1B work; no ADR chosen; no
provider key read; no production or host access. The disposable container, virtual environments and
scratch Python were removed after the runs (section 1 lists what was created).

## Appendix A. Throwaway proof files (not application code)

These are recorded only so the results can be reproduced. They are deliberately minimal and omit
everything an application needs. S1-T2 onward starts from the approved ADRs, not from these files.

`run_all.sh`:

```bash
#!/usr/bin/env bash
# Reproduce the S1-T1 proofs from scratch. Usage: run_all.sh <path-to-venv-python>
# Disposable: one uniquely named container on loopback, tmpfs storage, synthetic data only.
set -euo pipefail
PY="$1"; HERE="$(cd "$(dirname "$0")" && pwd)"; NAME=s1t1-pg-disposable
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_PASSWORD=synthetic-test-only -e POSTGRES_DB=s1t1 -p 127.0.0.1:55432:5432 postgres:16 >/dev/null
until docker exec "$NAME" pg_isready -U postgres -d s1t1 >/dev/null 2>&1; do sleep 1; done; sleep 2
cd "$HERE/proj"
echo "== versions: $("$PY" -c 'import sys,django,psycopg,procrastinate;print(sys.version.split()[0],"django",django.get_version(),"psycopg",psycopg.__version__,"procrastinate",procrastinate.__version__)') postgres $(docker exec "$NAME" postgres --version | awk '{print $3}')"
"$PY" manage.py migrate -v0
echo "== migration order (custom user before admin):"; "$PY" manage.py showmigrations -p 2>/dev/null | grep -E 'auth.0001|accounts.0001|admin.0001' | head -3
echo "== demo 1: atomic enqueue";        "$PY" demo_atomic.py 2>&1 | grep -v instantiated
echo "== demo 2a: Procrastinate crash";  "$PY" demo_crash_procrastinate.py 2>&1 | grep -v instantiated
echo "== demo 2b: custom ledger crash";  "$PY" demo_crash_ledger.py
docker exec -i "$NAME" psql -q -v ON_ERROR_STOP=1 -U postgres -d s1t1 < append_only.sql
echo "== demo 3: append-only";           "$PY" demo_append_only.py
echo "== demo 3 owner limits:"; docker exec "$NAME" psql -U postgres -d s1t1 -c "truncate demo_historyevent" 2>&1 | grep -o 'append-only.*' || true
docker exec "$NAME" psql -U postgres -d s1t1 -Atc "begin; alter table demo_historyevent disable trigger history_no_update_delete; select 'owner CAN disable the trigger'; rollback;" 2>&1 | grep owner
```

`proj/settings.py`:

```python
# Throwaway S1-T1 compatibility proof. Synthetic data only. Not application code.
SECRET_KEY = "synthetic-test-only"
USE_TZ = True; TIME_ZONE = "UTC"; DEBUG = False; ALLOWED_HOSTS = ["localhost"]
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "django.contrib.admin",
                  "django.contrib.sessions", "django.contrib.messages", "accounts", "demo",
                  "procrastinate.contrib.django"]
AUTH_USER_MODEL = "accounts.User"
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "s1t1", "USER": "postgres",
             "PASSWORD": "synthetic-test-only", "HOST": "127.0.0.1", "PORT": "55432", "ATOMIC_REQUESTS": False}}
ROOT_URLCONF = "settings"; urlpatterns = []
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIDDLEWARE = ["django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
              "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware"]
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.request",
              "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
```

`proj/manage.py`:

```python
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
from django.core.management import execute_from_command_line
execute_from_command_line(sys.argv)
```

`proj/accounts/models.py`:

```python
from django.contrib.auth.models import AbstractUser
class User(AbstractUser):
    """Minimal custom user (ADR-18 candidate): staff accounts only."""
```

`proj/demo/models.py`:

```python
import uuid
from django.db import models
class Application(models.Model):          # applicant dossier record: no FK to the user model
    email_key = models.CharField(max_length=320, unique=True)
class PendingAction(models.Model):        # custom-ledger candidate (subject-generic, no FK)
    kind = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=16, default="queued")
    attempts = models.IntegerField(default=0); max_attempts = models.IntegerField(default=3)
    lease_token = models.UUIDField(null=True); lease_expires_at = models.DateTimeField(null=True)
class HistoryEvent(models.Model):         # append-only candidate (ADR-14)
    application = models.ForeignKey(Application, on_delete=models.PROTECT)
    kind = models.CharField(max_length=64)
```

`proj/demo/apps.py`:

```python
from django.apps import AppConfig
class DemoConfig(AppConfig):
    name = "demo"
    def ready(self):
        from . import tasks  # noqa: F401
```

`proj/demo/tasks.py`:

```python
import time
from procrastinate.contrib.django import app
@app.task(name="send_verification", queue="default")
def send_verification(application_id, sleep=0):
    time.sleep(sleep)   # stands in for a provider call
```

`proj/demo_atomic.py`:

```python
# Demo 1: atomic enqueue. Observer is a separate psycopg connection (not Django's).
import os, django, psycopg
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"; django.setup()
from django.db import transaction
from demo.models import Application, PendingAction
from demo.tasks import send_verification
DSN = "host=127.0.0.1 port=55432 dbname=s1t1 user=postgres password=synthetic-test-only"
def seen(email):
    with psycopg.connect(DSN, autocommit=True) as o:
        a = o.execute("select count(*) from demo_application where email_key=%s", [email]).fetchone()[0]
        j = o.execute("select count(*) from procrastinate_jobs where args->>'application_id'=%s", [email]).fetchone()[0]
        l = o.execute("select count(*) from demo_pendingaction where subject_id=%s", [email]).fetchone()[0]
        return a, j, l
class Boom(Exception): pass
def run(label, email, enqueue, fail):
    try:
        with transaction.atomic():
            Application.objects.create(email_key=email)
            enqueue(email)
            if fail: raise Boom
    except Boom: pass
    print(f"{label:<44} {'rollback' if fail else 'commit  '} -> app,procrastinate_job,ledger_row = {seen(email)}")
pq = lambda e: send_verification.defer(application_id=e)
ledger = lambda e: PendingAction.objects.create(kind="send_verification", subject_id=e, idempotency_key=f"sv:{e}")
run("Procrastinate via Django connector", "a1@example.test", pq, True)
run("Procrastinate via Django connector", "a2@example.test", pq, False)
run("Custom ledger (ORM row)", "b1@example.test", ledger, True)
run("Custom ledger (ORM row)", "b2@example.test", ledger, False)
# Documented path: external psycopg connection, SyncPsycopgConnector (no Django)
from procrastinate import App, SyncPsycopgConnector
ext = App(connector=SyncPsycopgConnector(conninfo=DSN)); ext.open()
@ext.task(name="send_verification_ext")
def sv_ext(application_id): pass
for email, fail in (("c1@example.test", True), ("c2@example.test", False)):
    with psycopg.connect(DSN) as conn:
        conn.execute("insert into demo_application(email_key) values (%s)", [email])
        sv_ext.configure(connection=conn).defer(application_id=email)
        conn.rollback() if fail else conn.commit()
    print(f"{'Procrastinate external psycopg connection':<44} {'rollback' if fail else 'commit  '} -> app,procrastinate_job,ledger_row = {seen(email)}")
ext.close()
```

`proj/demo_crash_procrastinate.py`:

```python
# Demo 2a: Procrastinate worker killed with SIGKILL mid-job, then recovery.
import os, time, signal, subprocess, sys, asyncio, django, psycopg
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"; django.setup()
from procrastinate.contrib.django import app
from demo.tasks import send_verification
DSN = "host=127.0.0.1 port=55432 dbname=s1t1 user=postgres password=synthetic-test-only"
def status(jid):
    with psycopg.connect(DSN, autocommit=True) as o:
        return o.execute("select status, attempts from procrastinate_jobs where id=%s", [jid]).fetchone()
jid = send_verification.defer(application_id="crash@example.test", sleep=8)
w = subprocess.Popen([sys.executable, "manage.py", "procrastinate", "worker", "-q", "default"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    time.sleep(0.2)
    if status(jid)[0] == "doing": break
os.kill(w.pid, signal.SIGKILL); w.wait()
print("after SIGKILL mid-job:          ", status(jid))
time.sleep(12)
print("12 s later, nothing else run:   ", status(jid), "(no automatic recovery)")
async def recover():
    stalled = await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=10)
    for job in stalled:
        await app.job_manager.retry_job(job)
    return [j.id for j in stalled]
print("app-scheduled get_stalled_jobs + retry_job ->", asyncio.run(recover()), status(jid))
w2 = subprocess.run([sys.executable, "manage.py", "procrastinate", "worker", "-q", "default", "--one-shot"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
print("fresh worker --one-shot:        ", status(jid))
```

`proj/ledger_worker.py`:

```python
# Throwaway custom-ledger claim/complete (005 S1.4 rules 1-5), for the crash demo only.
import os, sys, time, uuid, django
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"; django.setup()
from django.db import transaction, connection
from django.db.models.functions import Now
from django.db.models import Q, F
from datetime import timedelta
from demo.models import PendingAction
LEASE = timedelta(seconds=60)
def claim():
    with transaction.atomic():
        row = (PendingAction.objects.select_for_update(skip_locked=True, of=("self",))
               .filter(Q(status="queued") | Q(status="running", lease_expires_at__lt=Now())).order_by("id").first())
        if row is None: return None
        if row.attempts >= row.max_attempts:                        # poison rule: never run again
            PendingAction.objects.filter(pk=row.pk).update(status="failed"); return ("poisoned", row.pk)
        tok = uuid.uuid4()
        PendingAction.objects.filter(pk=row.pk).update(status="running", lease_token=tok,
            lease_expires_at=Now() + LEASE, attempts=F("attempts") + 1)    # attempts counted at claim
        return (row.pk, tok)
def complete(pk, tok):                                                 # fenced result write
    return PendingAction.objects.filter(pk=pk, status="running", lease_token=tok).update(status="done", lease_token=None)
if __name__ == "__main__":
    c = claim(); print("claimed", c, flush=True)
    if c and c[0] != "poisoned":
        time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 0)   # stands in for a provider call
        print("fenced complete rows:", complete(*c), flush=True)
```

`proj/demo_crash_ledger.py`:

```python
# Demo 2b: custom ledger worker killed with SIGKILL mid-action, recovery, lease fencing, poison rule.
import os, sys, time, signal, subprocess, django, psycopg
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"; django.setup()
from demo.models import PendingAction
import ledger_worker as lw
DSN = "host=127.0.0.1 port=55432 dbname=s1t1 user=postgres password=synthetic-test-only"
def st(pk): r = PendingAction.objects.get(pk=pk); return (r.status, r.attempts)
def expire(pk):  # simulate lease expiry with the database clock, no clock mocking
    with psycopg.connect(DSN, autocommit=True) as o:
        o.execute("update demo_pendingaction set lease_expires_at = now() - interval '1 second' where id=%s", [pk])
PendingAction.objects.all().delete()   # isolate: start from an empty ledger
a = PendingAction.objects.create(kind="send_verification", subject_id="k@example.test", idempotency_key="sv:k")
w = subprocess.Popen([sys.executable, "ledger_worker.py", "30"], stdout=subprocess.PIPE, text=True)
claimed_line = w.stdout.readline(); os.kill(w.pid, signal.SIGKILL); w.wait()
print("worker said:", claimed_line.strip())
print("after SIGKILL mid-action:              ", st(a.pk))
print("second worker while lease live:        ", lw.claim(), st(a.pk))
old_tok = PendingAction.objects.get(pk=a.pk).lease_token
expire(a.pk); c = lw.claim()
print("after lease expiry, reclaimed:         ", c[0] == a.pk, st(a.pk))
print("stale worker's late write (old token): ", lw.complete(a.pk, old_tok), "rows")
print("current worker's fenced write:         ", lw.complete(*c), "rows", st(a.pk))
p = PendingAction.objects.create(kind="send_verification", subject_id="p@example.test", idempotency_key="sv:p",
                                 status="running", attempts=3, max_attempts=3)
expire(p.pk); print("poison: claim at max attempts ->       ", lw.claim(), st(p.pk))
from django.db import IntegrityError
try: PendingAction.objects.create(kind="send_verification", subject_id="k@example.test", idempotency_key="sv:k")
except IntegrityError: print("duplicate idempotency key:              refused by unique constraint")
```

`proj/append_only.sql`:

```sql
-- Throwaway ADR-14 proof. Roles: postgres = schema owner (migrations), catalyst_app = the web/worker
-- login (DML only, not owner), catalyst_retention = the privileged retention/deletion path.
CREATE ROLE catalyst_app LOGIN PASSWORD 'synthetic-test-only';
CREATE ROLE catalyst_retention LOGIN PASSWORD 'synthetic-test-only';
GRANT USAGE ON SCHEMA public TO catalyst_app, catalyst_retention;
GRANT SELECT, INSERT, UPDATE, DELETE ON demo_application, demo_historyevent TO catalyst_app, catalyst_retention;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO catalyst_app, catalyst_retention;
CREATE TABLE retention_audit (id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  actor name NOT NULL, tbl text NOT NULL, row_id bigint NOT NULL, reason text NOT NULL);
GRANT SELECT ON retention_audit TO catalyst_app, catalyst_retention;   -- nobody but the trigger inserts
CREATE FUNCTION history_append_only() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
BEGIN
  IF TG_OP = 'DELETE' AND pg_has_role(session_user, 'catalyst_retention', 'MEMBER')
     AND coalesce(current_setting('catalyst.retention_reason', true), '') <> '' THEN
    INSERT INTO retention_audit(actor, tbl, row_id, reason)
      VALUES (session_user, TG_TABLE_NAME, OLD.id, current_setting('catalyst.retention_reason'));
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'append-only: % on % refused for %', TG_OP, TG_TABLE_NAME, session_user
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER history_no_update_delete BEFORE UPDATE OR DELETE ON demo_historyevent
  FOR EACH ROW EXECUTE FUNCTION history_append_only();
CREATE FUNCTION history_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'append-only: TRUNCATE on % refused', TG_TABLE_NAME; END $$;
CREATE TRIGGER history_no_truncate BEFORE TRUNCATE ON demo_historyevent
  FOR EACH STATEMENT EXECUTE FUNCTION history_no_truncate();
```

`proj/demo_append_only.py`:

```python
# Demo 3: append-only history for ordinary writes; privileged, audited retention delete.
import os, django, psycopg
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"
from django.conf import settings
django.setup()
from django.db import connections, transaction
base = dict(settings.DATABASES["default"])
connections.settings["app"] = {**base, "USER": "catalyst_app", "PASSWORD": "synthetic-test-only"}
from demo.models import Application, HistoryEvent
def attempt(label, fn):
    try:
        with transaction.atomic(using="app"): fn()
        print(f"{label:<52} ALLOWED")
    except Exception as e:
        print(f"{label:<52} REFUSED ({type(e).__name__}: {str(e).splitlines()[0][:60]})")
a = Application.objects.using("app").create(email_key="h@example.test")
ev = HistoryEvent.objects.using("app").create(application=a, kind="submission_received")
attempt("app role: insert a new event (append)", lambda: HistoryEvent.objects.using("app").create(application=a, kind="x"))
attempt("app role: ORM .update() on an event", lambda: HistoryEvent.objects.using("app").filter(pk=ev.pk).update(kind="y"))
attempt("app role: ORM .delete() on an event", lambda: HistoryEvent.objects.using("app").filter(pk=ev.pk).delete())
def raw(sql):
    with connections["app"].cursor() as c: c.execute(sql)
attempt("app role: raw SQL UPDATE", lambda: raw(f"update demo_historyevent set kind='z' where id={ev.pk}"))
attempt("app role: raw SQL TRUNCATE", lambda: raw("truncate demo_historyevent"))
attempt("app role: sets the reason and deletes (not member)", lambda: (raw("set local catalyst.retention_reason = 'x'"), raw(f"delete from demo_historyevent where id={ev.pk}")))
attempt("app role: ALTER TABLE ... DISABLE TRIGGER", lambda: raw("alter table demo_historyevent disable trigger history_no_update_delete"))
DSN = "host=127.0.0.1 port=55432 dbname=s1t1 user=catalyst_retention password=synthetic-test-only"
with psycopg.connect(DSN) as r:
    try:
        r.execute(f"delete from demo_historyevent where id={ev.pk}"); r.commit(); print(f"{'retention role, no reason given':<52} ALLOWED")
    except Exception as e:
        r.rollback(); print(f"{'retention role, no reason given':<52} REFUSED ({type(e).__name__})")
    r.execute("set local catalyst.retention_reason = 'synthetic retention test'")
    r.execute(f"delete from demo_historyevent where id={ev.pk}"); r.commit()
    print(f"{'retention role with reason: DELETE':<52} ALLOWED; audit rows:",
          r.execute("select actor, tbl, row_id, reason from retention_audit").fetchall())
    try:
        r.execute("set local catalyst.retention_reason = 'x'"); r.execute("update demo_historyevent set kind='q'"); r.commit()
        print(f"{'retention role: UPDATE':<52} ALLOWED")
    except Exception as e:
        r.rollback(); print(f"{'retention role: UPDATE (corrections are new rows)':<52} REFUSED ({type(e).__name__})")
```

Empty `__init__.py` files and `migrations/__init__.py` complete the two apps; `manage.py makemigrations accounts demo` generates their migrations.

## Appendix B. Raw output

Python 3.14.0 run (the 3.12.3 run is identical apart from the version line and random UUIDs):

```text
== versions: 3.14.0 django 5.2.18 psycopg 3.3.6 procrastinate 3.10.0 postgres 16.15
== migration order (custom user before admin):
[X]  auth.0001_initial
[X]  accounts.0001_initial
[X]  admin.0001_initial
== demo 1: atomic enqueue
Procrastinate via Django connector           rollback -> app,procrastinate_job,ledger_row = (0, 0, 0)
Procrastinate via Django connector           commit   -> app,procrastinate_job,ledger_row = (1, 1, 0)
Custom ledger (ORM row)                      rollback -> app,procrastinate_job,ledger_row = (0, 0, 0)
Custom ledger (ORM row)                      commit   -> app,procrastinate_job,ledger_row = (1, 0, 1)
Procrastinate external psycopg connection    rollback -> app,procrastinate_job,ledger_row = (0, 0, 0)
Procrastinate external psycopg connection    commit   -> app,procrastinate_job,ledger_row = (1, 1, 0)
== demo 2a: Procrastinate crash
after SIGKILL mid-job:           ('doing', 0)
12 s later, nothing else run:    ('doing', 0) (no automatic recovery)
app-scheduled get_stalled_jobs + retry_job -> [5] ('todo', 1)
fresh worker --one-shot:         ('succeeded', 2)
== demo 2b: custom ledger crash
worker said: claimed (3, UUID('cae4ffa3-8a91-4a0a-8a39-52ec75234241'))
after SIGKILL mid-action:               ('running', 1)
second worker while lease live:         None ('running', 1)
after lease expiry, reclaimed:          True ('running', 2)
stale worker's late write (old token):  0 rows
current worker's fenced write:          1 rows ('done', 2)
poison: claim at max attempts ->        ('poisoned', 4) ('failed', 3)
duplicate idempotency key:              refused by unique constraint
== demo 3: append-only
app role: insert a new event (append)                ALLOWED
app role: ORM .update() on an event                  REFUSED (ProgrammingError: append-only: UPDATE on demo_historyevent refused for catalys)
app role: ORM .delete() on an event                  REFUSED (ProgrammingError: append-only: DELETE on demo_historyevent refused for catalys)
app role: raw SQL UPDATE                             REFUSED (ProgrammingError: append-only: UPDATE on demo_historyevent refused for catalys)
app role: raw SQL TRUNCATE                           REFUSED (ProgrammingError: permission denied for table demo_historyevent)
app role: sets the reason and deletes (not member)   REFUSED (ProgrammingError: append-only: DELETE on demo_historyevent refused for catalys)
app role: ALTER TABLE ... DISABLE TRIGGER            REFUSED (ProgrammingError: must be owner of table demo_historyevent)
retention role, no reason given                      REFUSED (InsufficientPrivilege)
retention role with reason: DELETE                   ALLOWED; audit rows: [('catalyst_retention', 'demo_historyevent', 1, 'synthetic retention test')]
retention role: UPDATE (corrections are new rows)    REFUSED (InsufficientPrivilege)
== demo 3 owner limits:
append-only: TRUNCATE on demo_historyevent refused
owner CAN disable the trigger
```

Version line of the 3.12.3 run:

```text
== versions: 3.12.3 django 5.2.18 psycopg 3.3.6 procrastinate 3.10.0 postgres 16.15
```
