"""Minimal source evidence needed to continue signing timers without a second reminder.

This preserves delivery metadata, never job payloads, mail bodies or credentials. A new
snapshot is appended when the source changes; previous import evidence is never rewritten.
"""

import re

from . import mapping
from .models import ImportedRecord

TABLE = "signing_history"
KINDS = ("signing_reminder", "signing_link_send")


def read_jobs(cursor):
    cursor.execute(
        "SELECT id, kind, status, case_id, agreement_id, action_key, attempts, "
        "next_run_at, completed_at, outcome_unknown FROM job "
        "WHERE kind IN ('signing_reminder', 'signing_link_send') "
        "ORDER BY id"
    )
    rows = []
    for raw in cursor.fetchall():
        row = dict(raw)
        key = row.pop("action_key")
        if row["kind"] == "signing_link_send":
            if re.fullmatch(
                r"signing\.link:"
                + re.escape(str(row["agreement_id"]))
                + r":approver:[1-9][0-9]*",
                key,
            ):
                continue
            match = re.fullmatch(
                r"signing\.link:"
                + re.escape(str(row["agreement_id"]))
                + r":applicant:([1-9][0-9]*)",
                key,
            )
            # A future/unknown key shape must remain visible as incomplete evidence.
            row["applicant_round"] = int(match[1]) if match else None
        rows.append(row)
    return rows


def capture(importer, case, application):
    """Inside the per-person import transaction, for initial imports and top-ups alike."""
    from .source import aware

    rows = importer.by_case[case["id"]]
    jobs = importer.snap.signing_jobs
    for agreement in rows["agreement"]:
        evidence = {
            "schema": 1,
            "jobs_complete": jobs is not None,
            "agreement_id": agreement["id"],
            "case_state": case["state"],
            "agreement": {
                key: mapping.iso(agreement.get(key))
                for key in (
                    "document_type",
                    "status",
                    "provenance",
                    "provider_ref",
                    "external_ref",
                    "created_at",
                    "status_changed_at",
                )
            },
            "jobs": [
                {key: mapping.iso(aware(value)) for key, value in job.items()}
                for job in (jobs or [])
                if job["agreement_id"] == agreement["id"]
            ],
        }
        previous = (
            ImportedRecord.objects.filter(
                application=application,
                v1_table=TABLE,
                data__agreement_id=agreement["id"],
            )
            .order_by("-pk")
            .first()
        )
        if previous is not None and previous.data == evidence:
            continue
        revision = mapping.digest(
            {"previous": previous.pk if previous else None, "evidence": evidence}
        )
        key = f"{agreement['id']}:{revision}"
        ImportedRecord.objects.create(
            v1_table=TABLE,
            v1_id=key,
            application=application,
            kind=TABLE,
            occurred_at=agreement.get("status_changed_at"),
            data=evidence,
            run_ref=importer.run_ref,
        )
        importer.existing.add((TABLE, key))
        importer.created["firstgen.ImportedRecord"] += 1
