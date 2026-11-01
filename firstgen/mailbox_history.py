"""Append-only release, mailbox and delivery facts for a frozen-source handover.

Do not import job payloads, passwords or welcome content. Source account rows can
change in place; the original imported record alone is not a current snapshot.
"""

import re

from correspondence.common import Refused

from . import mapping
from .models import ImportedRecord

TABLE = "mailbox_history"
KINDS = ("case_auto_release", "mailbox_create", "welcome_send", "mailbox.issued_notice")
PATTERNS = {
    "case_auto_release": r"release\.auto:([^:]+):[^:]+:[^:]+:v[0-9]+",
    "mailbox_create": r"mailbox\.create:([^:]+):([^:]+)",
    "welcome_send": r"welcome\.send:([^:]+):([^:]+):r([1-9][0-9]*)",
    "mailbox.issued_notice": r"mailbox\.issued_notice:([^:]+):[^:]+",
}


def read_jobs(cursor):
    cursor.execute(
        "SELECT id, kind, status, case_id, action_key, attempts, next_run_at, "
        "completed_at, outcome_unknown FROM job WHERE kind = ANY(%s) ORDER BY id",
        [list(KINDS)],
    )
    rows = []
    for raw in cursor.fetchall():
        row = dict(raw)
        match = re.fullmatch(PATTERNS[row["kind"]], row.pop("action_key"))
        row.update(key_valid=bool(match), key_case_id=None, mailbox_id=None)
        if match:
            if row["kind"] == "mailbox.issued_notice":
                row["mailbox_id"] = match[1]
            else:
                row["key_case_id"] = match[1]
                if row["kind"] != "case_auto_release":
                    row["mailbox_id"] = match[2]
                if row["kind"] == "welcome_send":
                    row["welcome_round"] = int(match[3])
        rows.append(row)
    return rows


def address_digest(local, domain):
    return mapping.digest([local.lower(), domain.lower()])


def capture(importer, case, application):
    from .source import aware

    rows = importer.by_case[case["id"]]
    accounts = rows["mailbox_account"]
    ids = {a["id"] for a in accounts}
    jobs = importer.snap.mailbox_jobs
    evidence = {
        "schema": 1,
        "jobs_complete": jobs is not None,
        "tables_complete": not set(("mailbox_account", "case_release")).intersection(
            importer.snap.missing
        ),
        "case_id": case["id"],
        "case_state": case["state"],
        "accounts": [
            {
                **{
                    key: mapping.iso(a.get(key))
                    for key in (
                        "id",
                        "case_id",
                        "status",
                        "approved_at",
                        "create_requested_at",
                        "created_at_provider",
                        "welcome_send_started_at",
                        "welcome_sent_at",
                        "welcome_round",
                        "updated_at",
                    )
                },
                "address_sha256": address_digest(a["username"], a["domain"]),
            }
            for a in accounts
        ],
        "releases": [
            {
                key: mapping.iso(r.get(key))
                for key in (
                    "id",
                    "case_id",
                    "nda_agreement_id",
                    "ua_agreement_id",
                    "verified_at",
                )
            }
            for r in rows["case_release"]
        ],
        "jobs": [
            {key: mapping.iso(aware(value)) for key, value in j.items()}
            for j in (jobs or [])
            if j["case_id"] == case["id"]
            or j["key_case_id"] == case["id"]
            or j["mailbox_id"] in ids
            or (
                j["case_id"] is None and j["key_case_id"] is None and not j["key_valid"]
            )
        ],
    }
    previous = latest(application)
    if previous and previous.data == evidence:
        return
    revision = mapping.digest(
        {"previous": previous.pk if previous else None, "evidence": evidence}
    )
    key = f"{case['id']}:{revision}"
    ImportedRecord.objects.create(
        application=application,
        v1_table=TABLE,
        v1_id=key,
        kind=TABLE,
        occurred_at=case.get("state_changed_at"),
        data=evidence,
        run_ref=importer.run_ref,
    )
    importer.existing.add((TABLE, key))
    importer.created["firstgen.ImportedRecord"] += 1


def latest(application):
    return (
        ImportedRecord.objects.filter(application=application, v1_table=TABLE)
        .order_by("-pk")
        .first()
    )


def current(application, case_id):
    snapshot = latest(application)
    if (
        not snapshot
        or snapshot.data.get("schema") != 1
        or not snapshot.data.get("jobs_complete")
        or not snapshot.data.get("tables_complete")
    ):
        raise Refused("legacy_mailbox_history_incomplete")
    data = snapshot.data
    if data["case_id"] != case_id:
        raise Refused("legacy_mailbox_history_mismatch")
    ids = {a["id"] for a in data["accounts"]}
    for job in data["jobs"]:
        if (
            not job["key_valid"]
            or job["case_id"] != case_id
            or job["key_case_id"] not in (None, case_id)
            or (job["mailbox_id"] is not None and job["mailbox_id"] not in ids)
        ):
            raise Refused("legacy_mailbox_delivery_requires_reconciliation")
    return snapshot


def settled(application, case_id):
    snapshot = current(application, case_id)
    if any(
        job["outcome_unknown"]
        or job["status"] not in ("queued", "succeeded", "failed", "cancelled")
        or (job["status"] == "queued" and job["attempts"] != 0)
        for job in snapshot.data["jobs"]
    ):
        raise Refused("legacy_mailbox_delivery_requires_reconciliation")
    return snapshot
