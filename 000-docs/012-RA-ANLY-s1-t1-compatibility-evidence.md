# S1-T1 Compatibility and Comparison Evidence (handoff 1A)

| Field | Value |
|---|---|
| Document | `012-RA-ANLY-s1-t1-compatibility-evidence` |
| Version | 0.2.0 (independent review findings applied; proofs re-run on exact Python patches) |
| Status | **EVIDENCE.** The owner decided ADR-03, ADR-14, ADR-17 and ADR-18 on 2026-10-10 against this evidence (D-16 to D-19, recorded on the ADR rows in `003`); the evidence below is unchanged. Nothing here is application code or a migration. |
| Owner | Jeremy Longshore |
| Date | 2026-10-09 |
| Bead | S1-T1, "Select and verify the Django, Python, PostgreSQL, driver and job-runner versions for the first slice" |
| Brief | `005` S1.6a; contract approval `011` section 10 |
| Classification | Public; synthetic data and a throwaway test password only; no provider keys read; no production contact |

> **Status: PRELIMINARY, subject to review.** The 22 `TEST-S1-` cases remain **NOT RUN**. The proofs
> below are throwaway compatibility checks, run in a disposable environment outside this repository.

## 1. How the evidence was produced

- **Environment:** the session's private scratch directory, outside the repository. Each run creates a
  private Docker network, a tmpfs PostgreSQL 16 container and a container from the official Python image,
  with no host port and no global install. It removes all three on exit. Data is synthetic
  (`example.test`).
- **Interpreters:** the official `python:3.14.8-slim` and `python:3.12.15-slim` images, the current
  patches of both lines. Both full outputs are in appendix B. An earlier pass on 3.14.0 and the system's
  3.12.3 is superseded.
- **Packages:** Django 5.2.18, psycopg 3.3.6 (binary), Procrastinate 3.10.0 with its Django extra;
  PostgreSQL 16.15 (`postgres:16` image).
- **Reproduce:** recreate the files in appendix A in one directory, then run
  `bash run_all.sh python:3.14.8-slim` (or `python:3.12.15-slim`). The run generates migrations, applies
  them, runs every proof and prints the measurements.

**Evidence labels** (mapped to the charter's tags, `007` section 6):

| Label here | Meaning | Charter tag |
|---|---|---|
| DEMONSTRATED | observed in the proof output in appendix B, with these versions | VERIFIED (primary: the run itself) |
| DOCUMENTED | stated by an official source read for this report (named in section 5) | VERIFIED |
| SOURCE-READ | read in the installed package's own code | VERIFIED |
| REPORTED | taken from another review or package metadata, not checked further | INSPECTED |
| ASSESSED | a judgement drawn from the above | INFERRED |

## 2. Results (identical on Python 3.14.8 and 3.12.15)

| # | Proof | Result |
|---|---|---|
| 1 | Atomic enqueue: the observer is a separate autocommit psycopg connection, not Django's. Each path inserts an application row and a job row, then rolls back (expect neither) or commits (expect both visible to the observer). | **PASS** for Procrastinate through Django's own connection (`transaction.atomic`), for the custom ledger (an ORM row) and for Procrastinate's documented external psycopg connection (`configure(connection=...)`) |
| 2a | Procrastinate worker killed with SIGKILL mid-job, **no** stalled-job task configured | job stays `doing` after 12 s, because nothing was configured to recover it; one manual `get_stalled_jobs()` + `retry_job()` call returns it to `todo`; a fresh worker completes it |
| 2c | Procrastinate worker A killed with SIGKILL; live worker B runs the documented periodic stalled-job task (every 5 s; stall threshold 15 s) | **recovered and completed with no manual step**, in 23 s (3.14.8) and 24 s (3.12.15). Defaults (SOURCE-READ): heartbeat every 10 s, worker pruned after 30 s |
| 2b | Custom-ledger worker killed with SIGKILL mid-action | row stays `running` under its live lease; a claim call while the lease is live gets nothing; after the lease is **forced past** (an `UPDATE` with the database's `now()`; the claim compares against the database clock), the next claim call reclaims it with attempts counted at claim; the stale worker's late write updates **0 rows**; the current worker's fenced write updates 1; a row at its attempt limit becomes `failed` without running; a duplicate idempotency key is refused. There is no polling loop in the proof: each claim is one explicit call |
| 3 | Append-only history: three non-superuser roles, privileges plus a trigger | the application role can append; its ORM `update()`/`delete()`, raw `UPDATE`, `TRUNCATE` and setting the retention reason are all refused by **privilege**, and disabling the trigger is refused (not the owner). The non-superuser owner is refused `UPDATE` and `TRUNCATE` by the **trigger**, but **can disable the trigger**. The retention role is refused a delete without a reason (trigger) and any `UPDATE` (privilege). It may delete with a reason, and each delete writes an audit row to `public.retention_audit`, even after it creates a temporary table named `retention_audit` to shadow it |
| 4 | Minimal custom user before the first migration | `accounts.0001_initial` (custom `AbstractUser`) applies before `admin.0001_initial`. The applicant model has no foreign key to the user model; history actor references to users were not exercised |
| 5a | Procrastinate duplicate protection (`queueing_lock`) inside the caller's transaction | the second `defer` with the same lock, wrapped in a savepoint as the docs advise, raises `AlreadyEnqueued`; the outer transaction commits one application row and one job |
| 5b | Procrastinate job retried while its first worker is still running it (a false stall) | the effect ran **twice** (2 effect rows); the job ends `succeeded` with 2 attempts; nothing stops the first worker's completion write |
| 5c | Custom ledger, the same late-worker situation | the late worker's database write is refused (0 rows), but the effect still ran **twice** (2 effect rows) |

**Not tested:** the ledger poison rule's history event and its `uncertain` variant (`005` S1.4 rule 2);
per-subject pause on either candidate; reconciliation of an `uncertain` outcome; Procrastinate's admin.

## 3. Decision table (for the owner; nothing chosen here)

| ADR | Recommendation | Evidence | Alternatives | Limitations | What the owner approves |
|---|---|---|---|---|---|
| ADR-03 job mechanism | **Lean towards the custom domain ledger** (the `005` S1.4 rules) as the single source of truth for pending work, run by a management-command worker. **This is a close call**: Procrastinate passed every behaviour it was tested on. | Proofs 1, 2a to 2c, 5a to 5c; section 4 | Procrastinate 3.10.0 as the runner, plus a domain table for pause, `uncertain` and staff state; Django's tasks interface through the `django-tasks` 0.12.0 backport (declares Django 5.2 support, REPORTED; not demonstrated, because this handoff was bounded to one library) | We write and test the worker loop ourselves: polling, backoff, signals, logging, a dead-worker monitor. Neither candidate stops a duplicate external effect after a false or real stall (5b, 5c) | the mechanism; that S1-T5 builds it; the condition for revisiting (section 4) |
| ADR-14 append-only | **Privileges plus trigger, with three non-superuser roles.** The application may append history only. The retention role may delete only with a stated reason, audited by a `SECURITY DEFINER` trigger with `search_path = public, pg_temp` and a schema-qualified audit table. The owner role runs migrations only, and no application process connects as owner or superuser | Proof 3 | privileges only (no protection against an owner mistake or a mis-grant); ORM guards only (proof 3 shows raw SQL and `QuerySet.update()` exist); the TEST-S1-21 architecture-test fallback | The owner can disable the trigger, so migrations need review for trigger changes. A superuser bypasses everything. Retention here **deletes** rows; if POL-10 requires redaction instead, the retention path needs a second, separately audited operation. The proof hardens the audit insert against a temporary-table shadow; whether the unhardened form was actually exploitable was not tested | the three-role model and trigger; that retention deletes until POL-10 decides |
| ADR-17 versions | **Django 5.2.18 (LTS), PostgreSQL 16.15, psycopg 3.3.6**, and **Python: owner's choice between 3.12.15 and 3.14.8**. Both passed every proof. 3.12 is what the approved contract proposed. 3.14 is a **change** from that proposal, with longer support (section 5). Procrastinate 3.10.0 only if ADR-03 picks it. Test tooling pytest 9.1.1 and pytest-django 4.14.0 is DOCUMENTED by package metadata only; it was not run here | Proofs on both images; section 5 | Django 6.1.2 (not LTS); PostgreSQL 17.11 or 18.6 (longer support) | pytest and pytest-django are not demonstrated. The production host's PostgreSQL version was not checked, which was outside this handoff's authority. The Ubuntu 24.04 system interpreter is 3.12.3, not 3.12.15 | exact versions, and the Python line |
| ADR-18 user model | **Minimal `accounts.User(AbstractUser)`** with no extra fields, set as `AUTH_USER_MODEL` before the first migration. Users are staff only; applicants are dossier records with no foreign key to users | Proof 4; Django 5.2 documentation | Django's default `User` (changing it later "can be complex"); a custom authentication system (out of scope) | Proof 4 is close to true by construction (one model, no foreign key); it shows the migration order, not a full application | the model and its place in the first migration |

## 4. ADR-03 comparison against the required behaviour

| Required behaviour | Custom domain ledger | Procrastinate 3.10.0 |
|---|---|---|
| Enqueue in the same transaction as the domain write | DEMONSTRATED (proof 1) | DEMONSTRATED through Django's own connection, and through the documented external psycopg connection (proof 1). SOURCE-READ: the Django connector runs SQL on `connections[alias]`. DOCUMENTED: the external-connection guide lists `SyncPsycopgConnector`, `PsycopgConnector` and `SQLAlchemyPsycopg2Connector`, and does not mention the Django connector |
| Worker-death recovery | DEMONSTRATED: the next claim takes rows whose lease has passed (2b). Production needs a polling worker loop that we write | DEMONSTRATED automatic once the application registers a periodic stalled-job task (2c; about 5 lines). Without one, nothing recovers (2a). Pitfall found while testing: its cron puts seconds in the **sixth** field (`* * * * * */5`), and getting this wrong silently runs the task every five minutes (observed during this work; that failed run's output was not retained) |
| Duplicate protection | DEMONSTRATED: unique idempotency key (2b) | DEMONSTRATED: `queueing_lock` refuses a second job; the call needs a savepoint inside the caller's transaction (5a) |
| Late worker after a stall | DEMONSTRATED: fenced database write refused (2b, 5c) | DEMONSTRATED: both executions ran (2 effect rows) and the job ended `succeeded` (5b); the first worker's own completion write was not observed separately, and the stall was simulated with `retry_job_by_id` |
| Duplicate external effect after a stall | DEMONSTRATED: still happens (5c) | DEMONSTRATED: still happens (5b) |
| `uncertain` outcomes and reconciliation | ASSESSED: an explicit status in the domain model (designed in `005` S1.4, not demonstrated); reconciliation is domain code either way | SOURCE-READ: job statuses are todo, doing, succeeded, failed, cancelled, aborting, aborted; there is no `uncertain`; ASSESSED: the domain still needs its own state |
| Per-subject pause that still lets staff messages run | ASSESSED: designed into the claim (`005` S1.4 rules 1 and 8); not demonstrated | ASSESSED: no per-subject pause in the job model; it needs a domain gate checked by each task, or cancel and re-defer; not demonstrated |
| Staff visibility | ASSESSED: the ledger is a domain model, so read-only admin works like any other model | SOURCE-READ: a bundled read-only Django admin for jobs (add, change and delete return false) |
| Maintenance burden | DEMONSTRATED: the core claim and fence is 27 lines (`ledger_worker.py`). ASSESSED: a production worker is a few hundred lines plus tests, all owned by us | 6 extra packages beyond what Django and psycopg already need (`attrs`, `croniter`, `packaging`, `psycopg-pool`, `python-dateutil`, `six`), 7 on Python 3.13 and later where psycopg no longer needs `typing-extensions` (REPORTED: PyPI `requires_dist` of Django 5.2.18, psycopg 3.3.6, Procrastinate 3.10.0 and their dependencies; the installed set is in appendix B); DEMONSTRATED: 4 tables and 18 database functions under its own migrations. REPORTED (PyPI): releases 3.7.0 to 3.10.0 between January and September 2026. INFERRED: its docs say it is tested with the latest Django for each Python, so Django 5.2 may be outside its stated matrix; the proofs here passed on 5.2.18 |
| Useful extras | none | built-in periodic (cron) tasks; LISTEN/NOTIFY wake-ups; a mature async worker |

**Why the lean is towards the custom ledger (ASSESSED; the owner weighs it).** Procrastinate meets
every behaviour that was tested: transactional enqueue, automatic recovery with a periodic task, and
duplicate protection. The difference is where the state lives.

The first slice and the journey need per-application pause that still lets staff messages through, an
`uncertain` state, held actions and a staff view of all pending work (`004`, `005` S1.4). With
Procrastinate, all of that becomes a domain table beside its job table, so the pending-work state lives in
two places. It also brings 6 or 7 packages, 4 tables and 18 functions.

The custom ledger keeps one table and gives a fenced write (5c), at the cost of a worker loop we build and
test ourselves. Neither one prevents a duplicate provider effect (5b, 5c). That stays the job of
idempotent providers and the `uncertain` and reconcile path (ADR-15).

**Revisit if** later phases need cron-style schedules beyond due-time rows, or low-latency wake-ups.
Both are Procrastinate strengths.

## 5. Versions and support statements (sources read 2026-10-09)

| Component | Proposed | Support statement | Source |
|---|---|---|---|
| Django | 5.2.18 | 5.2 LTS: latest release 5.2.18, extended support until April 2028. 6.1: latest 6.1.2, extended support until December 2027. Next LTS: 6.2, April 2027 | djangoproject.com "Download", supported-versions table |
| Django and Python | 3.10 to 3.14 | "Django 5.2 supports Python 3.10, 3.11, 3.12, 3.13, and 3.14 (as of 5.2.8)" | Django 5.2 release notes, "Python compatibility" |
| Django and PostgreSQL, psycopg | PostgreSQL 14+; psycopg 3.1.8+ | "Django supports PostgreSQL 14 and higher. psycopg 3.1.8+ or psycopg2 2.8.4+ is required" | Django 5.2 docs, "Databases", PostgreSQL notes |
| Python | 3.12.15 or 3.14.8 | 3.14: status bugfix, end of life 2030-10. 3.13: security, 2029-10. 3.12: security, 2028-10. End-of-life dates are scheduled and can be adjusted. The table shows no separate bugfix-end date | devguide.python.org "Status of Python versions"; current patches from python.org "Downloads" |
| PostgreSQL | 16.15 | 16: current minor 16.15, final release November 9, 2028. 17.11: until November 8, 2029. 18.6: until November 14, 2030 | postgresql.org "Versioning policy" |
| psycopg | 3.3.6 | latest on PyPI (2026-09-18); Python 3.10 and later | PyPI |
| pytest | 9.1.1 | classifiers for Python 3.12 to 3.14; not run here | PyPI (REPORTED) |
| pytest-django | 4.14.0 | classifiers for Django 5.2 and 6.0 and Python 3.12 to 3.14; not run here | PyPI (REPORTED) |
| Procrastinate | 3.10.0 (only if chosen) | Python 3.10 and later; `django>=2.2` extra | PyPI; Procrastinate Django docs |

Nothing was copied from an older worktree. Every version comes from these sources.

## 6. What 1A did not do

No application code, project skeleton or migration in this repository. No 1B work. No ADR chosen. No
provider key read. No production or host access. Each run removes its own containers and network on exit.
The earlier virtual environments, scratch Python and cache were removed. Only the proof sources and
outputs remain, in the private scratch directory and in the appendices below.

## Appendix A. Throwaway proof files (not application code)

These files are recorded only so the results can be reproduced. They are deliberately minimal and leave
out everything an application needs. S1-T2 onward starts from the approved ADRs, not from these files.
`manage.py makemigrations` generates the two apps' migrations inside the run.

`run_all.sh`:

```bash
#!/usr/bin/env bash
# Reproduce the S1-T1 proofs from scratch inside an exact Python image.
# Usage: run_all.sh python:3.14.8-slim
# Disposable: a private Docker network, a tmpfs PostgreSQL 16 container and a Python container,
# all named s1t1-*; no host port; synthetic data and a throwaway test password only.
set -euo pipefail
IMAGE="$1"; HERE="$(cd "$(dirname "$0")" && pwd)"; NET=s1t1-net; PG=s1t1-pg; PYC=s1t1-py
cleanup() { docker rm -f "$PG" "$PYC" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
cleanup; trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_PASSWORD=synthetic-test-only -e POSTGRES_DB=s1t1 postgres:16 >/dev/null
docker run -d --name "$PYC" --network "$NET" --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e PGHOST="$PG" -e PGPORT=5432 -v "$HERE/proj:/w" -w /w "$IMAGE" sleep infinity >/dev/null
docker exec "$PYC" python -m venv /tmp/v
docker exec "$PYC" /tmp/v/bin/pip install -q --disable-pip-version-check \
  "Django==5.2.18" "psycopg[binary]==3.3.6" "procrastinate[django]==3.10.0"
PY=(docker exec "$PYC" /tmp/v/bin/python)
until docker exec "$PG" pg_isready -U postgres -d s1t1 >/dev/null 2>&1; do sleep 1; done; sleep 2
echo "== versions: $("${PY[@]}" -c 'import sys,django,psycopg,procrastinate;print("python",sys.version.split()[0],"django",django.get_version(),"psycopg",psycopg.__version__,"procrastinate",procrastinate.__version__)') postgres $(docker exec "$PG" postgres --version | awk '{print $3}')"
"${PY[@]}" manage.py makemigrations accounts demo -v0
"${PY[@]}" manage.py migrate -v0
echo "== demo 4: migration order (custom user before admin)"; "${PY[@]}" manage.py showmigrations -p | grep -E 'auth.0001|accounts.0001|admin.0001'
echo "== demo 1: atomic enqueue";                 "${PY[@]}" demo_atomic.py 2>&1 | grep -v instantiated
echo "== demo 2a: Procrastinate, no recovery job"; "${PY[@]}" demo_crash_procrastinate.py 2>&1 | grep -v instantiated
echo "== demo 2c: Procrastinate, documented periodic recovery"; "${PY[@]}" demo_recovery_procrastinate.py 2>&1 | grep -v instantiated
echo "== demo 2b and 5c: custom ledger";          "${PY[@]}" demo_crash_ledger.py
echo "== demo 5a and 5b: Procrastinate duplicates"; "${PY[@]}" demo_dupe_procrastinate.py 2>&1 | grep -v instantiated
docker exec -i "$PG" psql -q -v ON_ERROR_STOP=1 -U postgres -d s1t1 < "$HERE/proj/append_only.sql"
echo "== demo 3: append-only";                    "${PY[@]}" demo_append_only.py
echo "== measurements"
echo "installed packages: $(docker exec "$PYC" /tmp/v/bin/pip list --format freeze --disable-pip-version-check | tr '\n' ' ')"
echo "procrastinate tables, functions: $(docker exec "$PG" psql -U postgres -d s1t1 -Atc "select (select count(*) from pg_tables where tablename like 'procrastinate%'), (select count(*) from pg_proc where proname like 'procrastinate%')")"
echo "worker heartbeat and stall defaults (procrastinate/worker.py): $(docker exec "$PYC" sh -c "grep -E -o '(update_heartbeat_interval|stalled_worker_timeout): float = [0-9.]+' /tmp/v/lib/python3*/site-packages/procrastinate/worker.py" | sort -u | tr '\n' ' ')"
echo "ledger_worker.py lines: $(wc -l < "$HERE/proj/ledger_worker.py")"
```

`proj/settings.py`:

```python
import os
# Throwaway S1-T1 compatibility proof. Synthetic data only. Not application code.
SECRET_KEY = "synthetic-test-only"
USE_TZ = True; TIME_ZONE = "UTC"; DEBUG = False; ALLOWED_HOSTS = ["localhost"]
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "django.contrib.admin",
                  "django.contrib.sessions", "django.contrib.messages", "accounts", "demo",
                  "procrastinate.contrib.django"]
AUTH_USER_MODEL = "accounts.User"
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "s1t1", "USER": "postgres",
             "PASSWORD": "synthetic-test-only", "HOST": os.environ.get("PGHOST", "127.0.0.1"), "PORT": os.environ.get("PGPORT", "55432"), "ATOMIC_REQUESTS": False}}
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
class Effect(models.Model):               # stands in for an external provider effect (one row per execution)
    key = models.CharField(max_length=64)
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
STALL_SECONDS = 15   # longer than the worker heartbeat interval (source: 10 s default)
@app.task(name="send_verification", queue="default")
def send_verification(application_id, sleep=0):
    time.sleep(sleep)   # stands in for a provider call
@app.task(name="provider_effect", queue="default")
def provider_effect(key, sleep=0):
    from demo.models import Effect
    time.sleep(sleep); Effect.objects.create(key=key)
@app.periodic(cron="* * * * * */5")       # every 5 seconds (6-field cron; seconds are the last field)
@app.task(name="retry_stalled", queue="maintenance", pass_context=True)
async def retry_stalled(context, timestamp):
    for job in await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=STALL_SECONDS):
        await app.job_manager.retry_job(job)
```

`proj/demo_atomic.py`:

```python
# Demo 1: atomic enqueue. Observer is a separate psycopg connection (not Django's).
import os, django, psycopg
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"; django.setup()
from django.db import transaction
from demo.models import Application, PendingAction
from demo.tasks import send_verification
DSN = f"host={os.environ.get('PGHOST', '127.0.0.1')} port={os.environ.get('PGPORT', '55432')} dbname=s1t1 user=postgres password=synthetic-test-only"
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
DSN = f"host={os.environ.get('PGHOST', '127.0.0.1')} port={os.environ.get('PGPORT', '55432')} dbname=s1t1 user=postgres password=synthetic-test-only"
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

`proj/demo_recovery_procrastinate.py`:

```python
# Demo 2c: Procrastinate recovery end to end: worker A killed; live worker B runs the periodic
# stalled-job task (documented pattern) and the job completes without manual steps.
import os, time, signal, subprocess, sys, django, psycopg
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"; django.setup()
from demo.tasks import send_verification, STALL_SECONDS
DSN = f"host={os.environ.get('PGHOST', '127.0.0.1')} port={os.environ.get('PGPORT', '55432')} dbname=s1t1 user=postgres password=synthetic-test-only"
def status(jid):
    with psycopg.connect(DSN, autocommit=True) as o:
        return o.execute("select status, attempts from procrastinate_jobs where id=%s", [jid]).fetchone()
W = [sys.executable, "manage.py", "procrastinate", "worker"]
jid = send_verification.defer(application_id="recover@example.test", sleep=4)
a = subprocess.Popen(W + ["-q", "default"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while status(jid)[0] != "doing": time.sleep(0.2)
os.kill(a.pid, signal.SIGKILL); a.wait(); t0 = time.time()
print("worker A killed mid-job:", status(jid))
b = subprocess.Popen(W + ["-q", "default,maintenance"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while status(jid)[0] != "succeeded" and time.time() - t0 < 120: time.sleep(1)
print(f"live worker B with periodic retry_stalled (stall threshold {STALL_SECONDS} s):", status(jid),
      f"after {time.time() - t0:.0f} s, no manual step")
b.send_signal(signal.SIGTERM); b.wait(timeout=30)
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
DSN = f"host={os.environ.get('PGHOST', '127.0.0.1')} port={os.environ.get('PGPORT', '55432')} dbname=s1t1 user=postgres password=synthetic-test-only"
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
# 5c: ledger equivalent of a late worker: the fence refuses the late DB write, but both workers
# already performed the effect (an Effect row per execution). Fences protect rows, not providers.
from demo.models import Effect
e = PendingAction.objects.create(kind="provider_effect", subject_id="late", idempotency_key="pe:late")
ca = lw.claim(); Effect.objects.create(key="ledger-late")          # worker A performs the effect, then stalls
expire(e.pk); cb = lw.claim(); Effect.objects.create(key="ledger-late")   # worker B reclaims and performs it again
print("5c ledger late worker: B fenced write", lw.complete(*cb), "row; A late write", lw.complete(*ca),
      "rows; effect rows =", Effect.objects.filter(key="ledger-late").count())
```

`proj/demo_dupe_procrastinate.py`:

```python
# Demo 5a: Procrastinate duplicate protection (queueing_lock) inside the caller's transaction, and
# 5b: a job retried while its first worker is still alive (a false stall) runs the effect twice.
import os, time, signal, subprocess, sys, django, psycopg
from datetime import datetime, timezone
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"; django.setup()
from django.db import transaction
from procrastinate import exceptions
from procrastinate.contrib.django import app
from demo.models import Application, Effect
from demo.tasks import send_verification, provider_effect
DSN = f"host={os.environ.get('PGHOST', '127.0.0.1')} port={os.environ.get('PGPORT', '55432')} dbname=s1t1 user=postgres password=synthetic-test-only"
def q(sql, args=()):
    with psycopg.connect(DSN, autocommit=True) as o: return o.execute(sql, args).fetchone()
with transaction.atomic():
    Application.objects.create(email_key="dupe@example.test")
    send_verification.configure(queueing_lock="sv:dupe").defer(application_id="dupe@example.test")
    try:
        with transaction.atomic():   # savepoint, as the docs advise
            send_verification.configure(queueing_lock="sv:dupe").defer(application_id="dupe@example.test")
        print("5a second defer: ACCEPTED")
    except exceptions.AlreadyEnqueued:
        print("5a second defer with the same queueing_lock: REFUSED (AlreadyEnqueued), outer transaction continues")
print("5a after commit: application rows, job rows =", q("select (select count(*) from demo_application where email_key='dupe@example.test'), (select count(*) from procrastinate_jobs where queueing_lock='sv:dupe')"))
W = [sys.executable, "manage.py", "procrastinate", "worker", "-q", "default"]
jid = provider_effect.defer(key="late", sleep=6)
a = subprocess.Popen(W, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while q("select status from procrastinate_jobs where id=%s", [jid])[0] != "doing": time.sleep(0.2)
app.job_manager.retry_job_by_id(jid, retry_at=datetime.now(timezone.utc))   # simulate a false stall
b = subprocess.Popen(W, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(16); a.send_signal(signal.SIGTERM); b.send_signal(signal.SIGTERM); a.wait(timeout=30); b.wait(timeout=30)
print("5b job retried while worker A still ran it: effect rows =", Effect.objects.filter(key="late").count(),
      "; final job status, attempts =", q("select status, attempts from procrastinate_jobs where id=%s", [jid]))
```

`proj/append_only.sql`:

```sql
-- Throwaway ADR-14 proof. Three login roles, none a superuser:
--   catalyst_owner     owns the tables and functions; runs migrations only
--   catalyst_app       the web and worker login: may append history, never change or remove it
--   catalyst_retention the privileged retention path: may delete history only with a stated reason, audited
CREATE ROLE catalyst_owner LOGIN PASSWORD 'synthetic-test-only';
CREATE ROLE catalyst_app LOGIN PASSWORD 'synthetic-test-only';
CREATE ROLE catalyst_retention LOGIN PASSWORD 'synthetic-test-only';
GRANT USAGE, CREATE ON SCHEMA public TO catalyst_owner;
GRANT USAGE ON SCHEMA public TO catalyst_app, catalyst_retention;
ALTER TABLE demo_application OWNER TO catalyst_owner;
ALTER TABLE demo_historyevent OWNER TO catalyst_owner;
SET ROLE catalyst_owner;
GRANT SELECT, INSERT, UPDATE ON demo_application TO catalyst_app;
GRANT SELECT ON demo_application TO catalyst_retention;
GRANT SELECT, INSERT ON demo_historyevent TO catalyst_app;            -- no UPDATE, DELETE, TRUNCATE
GRANT SELECT, DELETE ON demo_historyevent TO catalyst_retention;      -- no UPDATE, TRUNCATE
GRANT USAGE ON SEQUENCE demo_application_id_seq, demo_historyevent_id_seq TO catalyst_app;
CREATE TABLE public.retention_audit (id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  actor name NOT NULL, tbl text NOT NULL, row_id bigint NOT NULL, reason text NOT NULL);
GRANT SELECT ON public.retention_audit TO catalyst_app, catalyst_retention;  -- only the trigger inserts
CREATE FUNCTION public.history_append_only() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
BEGIN
  IF TG_OP = 'DELETE' AND pg_has_role(session_user, 'catalyst_retention', 'MEMBER')
     AND coalesce(current_setting('catalyst.retention_reason', true), '') <> '' THEN
    INSERT INTO public.retention_audit(actor, tbl, row_id, reason)
      VALUES (session_user, TG_TABLE_NAME, OLD.id, current_setting('catalyst.retention_reason'));
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'append-only: % on % refused for %', TG_OP, TG_TABLE_NAME, session_user
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER history_no_update_delete BEFORE UPDATE OR DELETE ON demo_historyevent
  FOR EACH ROW EXECUTE FUNCTION public.history_append_only();
CREATE FUNCTION public.history_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'append-only: TRUNCATE on % refused', TG_TABLE_NAME; END $$;
CREATE TRIGGER history_no_truncate BEFORE TRUNCATE ON demo_historyevent
  FOR EACH STATEMENT EXECUTE FUNCTION public.history_no_truncate();
RESET ROLE;
```

`proj/demo_append_only.py`:

```python
# Demo 3: append-only history: privileges plus a trigger; audited retention delete; owner limits.
import os, django, psycopg
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"
from django.conf import settings
django.setup()
from django.db import connections, transaction
connections.settings["app"] = {**settings.DATABASES["default"], "USER": "catalyst_app", "PASSWORD": "synthetic-test-only"}
from demo.models import Application, HistoryEvent
H, P = os.environ.get("PGHOST", "127.0.0.1"), os.environ.get("PGPORT", "55432")
def dsn(role): return f"host={H} port={P} dbname=s1t1 user={role} password=synthetic-test-only"
def say(label, ok, why=""): print(f"{label:<58} {'ALLOWED' if ok else 'REFUSED'}{' (' + why + ')' if why else ''}")
def attempt(label, fn):
    try:
        with transaction.atomic(using="app"): fn()
        say(label, True)
    except Exception as e: say(label, False, str(e).splitlines()[0][:70])
def raw(sql):
    with connections["app"].cursor() as c: c.execute(sql)
def as_role(role, label, *sql, commit=True):
    with psycopg.connect(dsn(role)) as c:
        try:
            for s in sql: c.execute(s)
            (c.commit() if commit else c.rollback()); say(label, True)
        except Exception as e: c.rollback(); say(label, False, str(e).splitlines()[0][:70])
a = Application.objects.using("app").create(email_key="h@example.test")
ev = HistoryEvent.objects.using("app").create(application=a, kind="submission_received")
ev2 = HistoryEvent.objects.using("app").create(application=a, kind="second")
attempt("app: append a new event", lambda: HistoryEvent.objects.using("app").create(application=a, kind="x"))
attempt("app: ORM .update() on an event", lambda: HistoryEvent.objects.using("app").filter(pk=ev.pk).update(kind="y"))
attempt("app: ORM .delete() on an event", lambda: HistoryEvent.objects.using("app").filter(pk=ev.pk).delete())
attempt("app: raw SQL UPDATE", lambda: raw(f"update demo_historyevent set kind='z' where id={ev.pk}"))
attempt("app: raw SQL TRUNCATE", lambda: raw("truncate demo_historyevent"))
attempt("app: sets the retention reason, then deletes", lambda: (raw("set local catalyst.retention_reason = 'x'"), raw(f"delete from demo_historyevent where id={ev.pk}")))
attempt("app: ALTER TABLE ... DISABLE TRIGGER", lambda: raw("alter table demo_historyevent disable trigger history_no_update_delete"))
as_role("catalyst_owner", "owner (not superuser): UPDATE an event", f"update demo_historyevent set kind='o' where id={ev.pk}")
as_role("catalyst_owner", "owner (not superuser): TRUNCATE", "truncate demo_historyevent")
as_role("catalyst_owner", "owner (not superuser): DISABLE TRIGGER (rolled back)", "alter table demo_historyevent disable trigger history_no_update_delete", commit=False)
as_role("catalyst_retention", "retention: DELETE without a reason", f"delete from demo_historyevent where id={ev.pk}")
as_role("catalyst_retention", "retention: UPDATE an event", "set local catalyst.retention_reason = 'x'", f"update demo_historyevent set kind='q' where id={ev.pk}")
as_role("catalyst_retention", "retention: DELETE with a reason", "set local catalyst.retention_reason = 'synthetic retention test'", f"delete from demo_historyevent where id={ev.pk}")
as_role("catalyst_retention", "retention: shadow the audit table with a temp table, then DELETE",
        "create temp table retention_audit (id bigserial, at timestamptz default now(), actor name, tbl text, row_id bigint, reason text)",
        "set local catalyst.retention_reason = 'shadow attempt'", f"delete from demo_historyevent where id={ev2.pk}")
with psycopg.connect(dsn("postgres"), autocommit=True) as o:
    print("public.retention_audit rows:", o.execute("select actor, row_id, reason from public.retention_audit order by id").fetchall())
```

Empty `__init__.py` files in `accounts/`, `demo/` and their `migrations/` directories complete the two apps.

## Appendix B. Raw output

`run_all.sh python:3.14.8-slim` (exit 0):

```text
== versions: python 3.14.8 django 5.2.18 psycopg 3.3.6 procrastinate 3.10.0 postgres 16.15
== demo 4: migration order (custom user before admin)
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
== demo 2a: Procrastinate, no recovery job
after SIGKILL mid-job:           ('doing', 0)
12 s later, nothing else run:    ('doing', 0) (no automatic recovery)
app-scheduled get_stalled_jobs + retry_job -> [5] ('todo', 1)
fresh worker --one-shot:         ('succeeded', 2)
== demo 2c: Procrastinate, documented periodic recovery
worker A killed mid-job: ('doing', 0)
live worker B with periodic retry_stalled (stall threshold 15 s): ('succeeded', 2) after 23 s, no manual step
== demo 2b and 5c: custom ledger
worker said: claimed (3, UUID('e4445388-d02f-429b-b2af-a9a98eb38491'))
after SIGKILL mid-action:               ('running', 1)
second worker while lease live:         None ('running', 1)
after lease expiry, reclaimed:          True ('running', 2)
stale worker's late write (old token):  0 rows
current worker's fenced write:          1 rows ('done', 2)
poison: claim at max attempts ->        ('poisoned', 4) ('failed', 3)
duplicate idempotency key:              refused by unique constraint
5c ledger late worker: B fenced write 1 row; A late write 0 rows; effect rows = 2
== demo 5a and 5b: Procrastinate duplicates
5a second defer with the same queueing_lock: REFUSED (AlreadyEnqueued), outer transaction continues
5a after commit: application rows, job rows = (1, 1)
5b job retried while worker A still ran it: effect rows = 2 ; final job status, attempts = ('succeeded', 2)
== demo 3: append-only
app: append a new event                                    ALLOWED
app: ORM .update() on an event                             REFUSED (permission denied for table demo_historyevent)
app: ORM .delete() on an event                             REFUSED (permission denied for table demo_historyevent)
app: raw SQL UPDATE                                        REFUSED (permission denied for table demo_historyevent)
app: raw SQL TRUNCATE                                      REFUSED (permission denied for table demo_historyevent)
app: sets the retention reason, then deletes               REFUSED (permission denied for table demo_historyevent)
app: ALTER TABLE ... DISABLE TRIGGER                       REFUSED (must be owner of table demo_historyevent)
owner (not superuser): UPDATE an event                     REFUSED (append-only: UPDATE on demo_historyevent refused for catalyst_owner)
owner (not superuser): TRUNCATE                            REFUSED (append-only: TRUNCATE on demo_historyevent refused)
owner (not superuser): DISABLE TRIGGER (rolled back)       ALLOWED
retention: DELETE without a reason                         REFUSED (append-only: DELETE on demo_historyevent refused for catalyst_retentio)
retention: UPDATE an event                                 REFUSED (permission denied for table demo_historyevent)
retention: DELETE with a reason                            ALLOWED
retention: shadow the audit table with a temp table, then DELETE ALLOWED
public.retention_audit rows: [('catalyst_retention', 1, 'synthetic retention test'), ('catalyst_retention', 2, 'shadow attempt')]
== measurements
installed packages: asgiref==3.12.1 attrs==26.1.0 croniter==6.2.4 Django==5.2.18 packaging==26.3 pip==26.2.1 procrastinate==3.10.0 psycopg==3.3.6 psycopg-binary==3.3.6 psycopg-pool==3.3.3 python-dateutil==2.9.0.post0 six==1.17.0 sqlparse==0.6.0 typing_extensions==4.16.0 
procrastinate tables, functions: 4|18
worker heartbeat and stall defaults (procrastinate/worker.py): stalled_worker_timeout: float = 30.0 update_heartbeat_interval: float = 10.0 
ledger_worker.py lines: 27
```

`run_all.sh python:3.12.15-slim` (exit 0):

```text
== versions: python 3.12.15 django 5.2.18 psycopg 3.3.6 procrastinate 3.10.0 postgres 16.15
== demo 4: migration order (custom user before admin)
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
== demo 2a: Procrastinate, no recovery job
after SIGKILL mid-job:           ('doing', 0)
12 s later, nothing else run:    ('doing', 0) (no automatic recovery)
app-scheduled get_stalled_jobs + retry_job -> [5] ('todo', 1)
fresh worker --one-shot:         ('succeeded', 2)
== demo 2c: Procrastinate, documented periodic recovery
worker A killed mid-job: ('doing', 0)
live worker B with periodic retry_stalled (stall threshold 15 s): ('succeeded', 2) after 24 s, no manual step
== demo 2b and 5c: custom ledger
worker said: claimed (3, UUID('a74270e5-50f5-4d50-9590-9ee3ececff67'))
after SIGKILL mid-action:               ('running', 1)
second worker while lease live:         None ('running', 1)
after lease expiry, reclaimed:          True ('running', 2)
stale worker's late write (old token):  0 rows
current worker's fenced write:          1 rows ('done', 2)
poison: claim at max attempts ->        ('poisoned', 4) ('failed', 3)
duplicate idempotency key:              refused by unique constraint
5c ledger late worker: B fenced write 1 row; A late write 0 rows; effect rows = 2
== demo 5a and 5b: Procrastinate duplicates
5a second defer with the same queueing_lock: REFUSED (AlreadyEnqueued), outer transaction continues
5a after commit: application rows, job rows = (1, 1)
5b job retried while worker A still ran it: effect rows = 2 ; final job status, attempts = ('succeeded', 2)
== demo 3: append-only
app: append a new event                                    ALLOWED
app: ORM .update() on an event                             REFUSED (permission denied for table demo_historyevent)
app: ORM .delete() on an event                             REFUSED (permission denied for table demo_historyevent)
app: raw SQL UPDATE                                        REFUSED (permission denied for table demo_historyevent)
app: raw SQL TRUNCATE                                      REFUSED (permission denied for table demo_historyevent)
app: sets the retention reason, then deletes               REFUSED (permission denied for table demo_historyevent)
app: ALTER TABLE ... DISABLE TRIGGER                       REFUSED (must be owner of table demo_historyevent)
owner (not superuser): UPDATE an event                     REFUSED (append-only: UPDATE on demo_historyevent refused for catalyst_owner)
owner (not superuser): TRUNCATE                            REFUSED (append-only: TRUNCATE on demo_historyevent refused)
owner (not superuser): DISABLE TRIGGER (rolled back)       ALLOWED
retention: DELETE without a reason                         REFUSED (append-only: DELETE on demo_historyevent refused for catalyst_retentio)
retention: UPDATE an event                                 REFUSED (permission denied for table demo_historyevent)
retention: DELETE with a reason                            ALLOWED
retention: shadow the audit table with a temp table, then DELETE ALLOWED
public.retention_audit rows: [('catalyst_retention', 1, 'synthetic retention test'), ('catalyst_retention', 2, 'shadow attempt')]
== measurements
installed packages: asgiref==3.12.1 attrs==26.1.0 croniter==6.2.4 Django==5.2.18 packaging==26.3 pip==25.0.1 procrastinate==3.10.0 psycopg==3.3.6 psycopg-binary==3.3.6 psycopg-pool==3.3.3 python-dateutil==2.9.0.post0 six==1.17.0 sqlparse==0.6.0 typing_extensions==4.16.0 
procrastinate tables, functions: 4|18
worker heartbeat and stall defaults (procrastinate/worker.py): stalled_worker_timeout: float = 30.0 update_heartbeat_interval: float = 10.0 
ledger_worker.py lines: 27
```
