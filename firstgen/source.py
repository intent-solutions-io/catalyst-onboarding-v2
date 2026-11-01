"""Read the first-generation database (bgl.16; 035 section 2). Read-only, one snapshot, nothing written there.

The source is untrusted data: every table is read with `SELECT *` into plain dicts (so a column added after
migration 0023 is carried, not refused), inside one REPEATABLE READ, READ ONLY transaction so every table is read at
the same instant. The job queue is counted, with open-job references and a narrow projection of signing
delivery metadata for timer handover. No job payload or credential is loaded. Times are the first
generation's naive UTC and become aware UTC here.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

# Every first-generation table this import reads row by row, with its primary key (034 section 1.5).
TABLES = {
    "onboarding_case": "id",
    "case_event": "id",
    "intake_request": "id",
    "intake_revision": "id",
    "applicant_credential": "id",
    "agreement": "id",
    "legacy_agreement_import": "agreement_id",
    "agreement_details": "id",
    "ua_details_capture": "envelope_id",
    "outbound_message": "id",
    "inbound_message": "id",
    "applicant_message": "id",
    "mailbox_cursor": "folder",
    "review_run": "id",
    "review_evidence": "id",
    "review_question": "id",
    "review_draft": "id",
    "crm_projection": "case_id",
    "crm_review_item": "id",
    "case_release": "id",
    "mailbox_account": "id",
}
# Operational tables: counted and summarised, never imported (035 section 2.9).
COUNTED = ("job", "intake_rate_event")
# Dormant tables, empty in production on 2026-10-31. A row in one is not mapped: the import reports it and fails.
DORMANT = (
    "setup_case",
    "setup_token",
    "setup_draft",
    "agreement_acceptance",
    "setup_job",
    "setup_details_snapshot",
    "interest_track_change",
)
OPEN_JOB_STATUSES = ("queued", "running", "reconciling", "needs_reconcile")


@dataclass
class Snapshot:
    rows: dict = field(default_factory=dict)  # {table: [row dict]}
    missing: list = field(default_factory=list)  # tables the source does not have
    counted: dict = field(default_factory=dict)  # {table: row count}
    job_counts: dict = field(default_factory=dict)  # {"kind/status": n}
    open_jobs: list = field(
        default_factory=list
    )  # [{"kind", "status", "case_id", "next_run_at", ...}]
    signing_jobs: list | None = (
        None  # payload-free delivery metadata; None means the job table was unavailable
    )
    dormant: dict = field(
        default_factory=dict
    )  # {table: row count}, only tables that exist
    fingerprint: str = ""


def aware(value):
    """A first-generation naive-UTC time as an aware UTC time (None stays None)."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _exists(cur, table) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", [table])
    return cur.fetchone()["present"]


def read(dsn: str) -> Snapshot:
    snap = Snapshot()
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction(), conn.cursor() as cur:
            for table, key in TABLES.items():
                if not _exists(cur, table):
                    snap.missing.append(table)
                    snap.rows[table] = []
                    continue
                cur.execute(
                    sql.SQL("SELECT * FROM {} ORDER BY {}").format(
                        sql.Identifier(table), sql.Identifier(key)
                    )
                )
                snap.rows[table] = [
                    {k: aware(v) for k, v in row.items()} for row in cur.fetchall()
                ]
            for table in COUNTED:
                if _exists(cur, table):
                    cur.execute(
                        sql.SQL("SELECT count(*) AS n FROM {}").format(
                            sql.Identifier(table)
                        )
                    )
                    snap.counted[table] = cur.fetchone()["n"]
                else:
                    snap.missing.append(table)
            if "job" in snap.counted:
                cur.execute(
                    "SELECT kind, status, count(*) AS n FROM job GROUP BY kind, status ORDER BY kind, status"
                )
                snap.job_counts = {
                    f"{r['kind']}/{r['status']}": r["n"] for r in cur.fetchall()
                }
                cur.execute(
                    "SELECT id, kind, status, case_id, agreement_id, next_run_at, outcome_unknown FROM job"
                    " WHERE status = ANY(%s) OR (status = 'failed' AND case_id IS NOT NULL)"
                    " ORDER BY next_run_at, id",
                    [list(OPEN_JOB_STATUSES)],
                )
                snap.open_jobs = [
                    {k: aware(v) for k, v in row.items()} for row in cur.fetchall()
                ]
                from .signing_history import read_jobs

                snap.signing_jobs = read_jobs(cur)
            for table in DORMANT:
                if _exists(cur, table):
                    cur.execute(
                        sql.SQL("SELECT count(*) AS n FROM {}").format(
                            sql.Identifier(table)
                        )
                    )
                    snap.dormant[table] = cur.fetchone()["n"]
    ids = sorted(f"{r['id']}:{r.get('state')}" for r in snap.rows["onboarding_case"])
    snap.fingerprint = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    return snap
