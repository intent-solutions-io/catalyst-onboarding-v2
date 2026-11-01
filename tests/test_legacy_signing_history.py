"""Signing handover retains the delivery facts v1 uses to avoid duplicate reminders."""

import json

from psycopg import sql

from firstgen import review, signing_history, source
from firstgen.models import ImportedCase, ImportedRecord
from tests.firstgen_v1 import new_id
from tests.test_first_generation_import import import_v1, populate, v1  # noqa: F401


def signing_job(
    v1, case_id, agreement_id, *, kind="signing_link_send", number=2, status="succeeded"
):
    job_id = new_id()
    key = (
        f"signing.link:{agreement_id}:applicant:{number}"
        if kind == "signing_link_send"
        else f"signing.reminder:{agreement_id}:r{number}"
    )
    v1.insert(
        "job",
        id=job_id,
        action_key=key,
        kind=kind,
        case_id=case_id,
        agreement_id=agreement_id,
        payload={"password": "synthetic-never-copy-job-payload"},
        status=status,
        attempts=1,
        next_run_at=v1.at(80),
        completed_at=v1.at(81),
        created_at=v1.at(79),
        updated_at=v1.at(81),
    )
    return job_id


def target(v1):
    ids = populate(v1)
    case_id = ids["CAT-ND00-0007"]
    agreement = v1.owner.execute(
        sql.SQL("SELECT id FROM {}.agreement WHERE case_id = %s").format(
            sql.Identifier(v1.schema)
        ),
        [case_id],
    ).fetchone()[0]
    return case_id, agreement


def history():
    case = ImportedCase.objects.get(reference="CAT-ND00-0007")
    return ImportedRecord.objects.filter(
        application=case.application, v1_table=signing_history.TABLE
    )


def test_signing_history_keeps_completed_resend_and_reminder_metadata_without_payloads(
    v1,
):
    case_id, agreement = target(v1)
    first = signing_job(v1, case_id, agreement, number=1)
    resend = signing_job(v1, case_id, agreement)
    reminder = signing_job(
        v1, case_id, agreement, kind="signing_reminder", status="needs_reconcile"
    )
    import_v1(v1)
    record = history().get()
    assert record.data["jobs_complete"] is True
    jobs = {job["id"]: job for job in record.data["jobs"]}
    assert set(jobs) == {first, resend, reminder}
    assert jobs[first]["applicant_round"] == 1 and jobs[resend]["applicant_round"] == 2
    assert jobs[reminder]["status"] == "needs_reconcile"
    assert jobs[resend]["completed_at"].endswith("+00:00")
    assert record.data["agreement"]["status"] == "sent"
    serialized = json.dumps(record.data)
    assert "synthetic-never-copy-job-payload" not in serialized
    assert "payload" not in serialized and "action_key" not in serialized


def test_signing_history_top_up_is_idempotent_but_preserves_a_changed_delivery(v1):
    case_id, agreement = target(v1)
    job = signing_job(v1, case_id, agreement, kind="signing_reminder", status="running")
    import_v1(v1)
    original = history().get()
    before = review.source_state(original.application)["sha256"]
    import_v1(v1)
    assert history().count() == 1
    v1.owner.execute(
        sql.SQL(
            "UPDATE {}.job SET status = 'succeeded', completed_at = %s WHERE id = %s"
        ).format(sql.Identifier(v1.schema)),
        [v1.at(90), job],
    )
    import_v1(v1)
    assert history().count() == 2
    original.refresh_from_db()
    assert original.data["jobs"][0]["status"] == "running"
    latest = history().order_by("-pk").first()
    assert latest.data["jobs"][0]["status"] == "succeeded"
    assert review.source_state(original.application)["sha256"] != before
    import_v1(v1)
    assert history().count() == 2
    # A source returning to an earlier state must not leave the newer, now-stale snapshot current.
    v1.owner.execute(
        sql.SQL(
            "UPDATE {}.job SET status = 'running', completed_at = %s WHERE id = %s"
        ).format(sql.Identifier(v1.schema)),
        [v1.at(81), job],
    )
    import_v1(v1)
    assert history().count() == 3
    assert history().order_by("-pk").first().data == original.data
    import_v1(v1)
    assert history().count() == 3


def test_unknown_resend_keys_and_missing_job_tables_are_not_treated_as_zero_history(v1):
    case_id, agreement = target(v1)
    job = signing_job(v1, case_id, agreement)
    v1.owner.execute(
        sql.SQL("UPDATE {}.job SET action_key = %s WHERE id = %s").format(
            sql.Identifier(v1.schema)
        ),
        [f"future.link:{agreement}:applicant:future-shape", job],
    )
    snapshot = source.read(v1.dsn)
    assert snapshot.signing_jobs[0]["applicant_round"] is None
    assert "action_key" not in snapshot.signing_jobs[0]
    v1.owner.execute(sql.SQL("DROP TABLE {}.job").format(sql.Identifier(v1.schema)))
    snapshot = source.read(v1.dsn)
    assert "job" in snapshot.missing and snapshot.signing_jobs is None
