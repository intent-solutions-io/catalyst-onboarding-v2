"""Re-import must observe changed effects without rewriting original evidence."""

import json

import pytest
from psycopg import sql

from correspondence.common import Refused
from firstgen import mailbox_history, review, source
from firstgen.models import ImportedCase, ImportedRecord
from provisioning.models import ProvisioningEvidence
from tests.firstgen_v1 import new_id
from tests.mxroute_fake import FakeMailHost
from tests.test_first_generation_import import import_v1, populate, v1  # noqa: F401
from tests.test_legacy_mailboxes import confirm, mailbox  # noqa: F401
from tests.test_legacy_release import pending, prepare  # noqa: F401
from tests.test_legacy_review import legacy  # noqa: F401
from workflow.models import PendingAction


def changed(v1, table, row_id, **fields):
    v1.owner.execute(
        sql.SQL("UPDATE {}.{} SET {} WHERE id = %s").format(
            sql.Identifier(v1.schema),
            sql.Identifier(table),
            sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(k)) for k in fields
            ),
        ),
        [*fields.values(), row_id],
    )


def job(
    v1, case_id, mailbox_id, *, kind="welcome_send", status="succeeded", attempts=1
):
    job_id = new_id()
    keys = {
        "welcome_send": f"welcome.send:{case_id}:{mailbox_id}:r1",
        "mailbox_create": f"mailbox.create:{case_id}:{mailbox_id}",
        "case_auto_release": f"release.auto:{case_id}:agreement:archived:v1",
        "mailbox.issued_notice": f"mailbox.issued_notice:{mailbox_id}:v1",
    }
    v1.insert(
        "job",
        id=job_id,
        kind=kind,
        action_key=keys[kind],
        case_id=case_id,
        payload={"password": "synthetic-not-for-import"},
        status=status,
        attempts=attempts,
        next_run_at=v1.at(99),
        completed_at=v1.at(99) if status == "succeeded" else None,
        created_at=v1.at(98),
        updated_at=v1.at(99),
    )
    return job_id


def account(v1, case_id):
    return v1.owner.execute(
        sql.SQL("SELECT id FROM {}.mailbox_account WHERE case_id = %s").format(
            sql.Identifier(v1.schema)
        ),
        [case_id],
    ).fetchone()[0]


def test_mailbox_top_up_preserves_current_round_and_original_evidence(v1):
    case_id = populate(v1)["CAT-AC00-0011"]
    mailbox_id = account(v1, case_id)
    for kind in mailbox_history.KINDS:
        job(v1, case_id, mailbox_id, kind=kind)
    import_v1(v1)
    application = ImportedCase.objects.get(v1_case_id=case_id).application
    original = mailbox_history.latest(application)
    original_account = ImportedRecord.objects.get(
        v1_table="mailbox_account", v1_id=mailbox_id
    )
    assert len(original.data["jobs"]) == 4
    serialized = json.dumps(original.data)
    assert "payload" not in serialized and "action_key" not in serialized
    assert "synthetic-not-for-import" not in serialized and "person11" not in serialized
    before = review.source_state(application)["sha256"]
    import_v1(v1)
    assert mailbox_history.latest(application).pk == original.pk
    changed(
        v1,
        "mailbox_account",
        mailbox_id,
        welcome_round=2,
        welcome_sent_at=None,
        welcome_send_started_at=v1.at(100),
    )
    import_v1(v1)
    latest = mailbox_history.latest(application)
    assert latest.pk != original.pk and latest.data["accounts"][0]["welcome_round"] == 2
    assert latest.data["accounts"][0]["welcome_sent_at"] is None
    original.refresh_from_db()
    original_account.refresh_from_db()
    assert original.data["accounts"][0]["welcome_sent_at"]
    assert original_account.data["welcome_sent_at"]
    assert review.source_state(application)["sha256"] != before
    changed(
        v1,
        "mailbox_account",
        mailbox_id,
        welcome_round=1,
        welcome_sent_at=v1.at(98),
        welcome_send_started_at=None,
    )
    import_v1(v1)
    assert mailbox_history.latest(application).pk > latest.pk
    assert mailbox_history.latest(application).data == original.data


def test_missing_job_or_mailbox_table_never_proves_absent_effects(v1):
    populate(v1)
    v1.owner.execute(sql.SQL("DROP TABLE {}.job").format(sql.Identifier(v1.schema)))
    snap = source.read(v1.dsn)
    assert snap.mailbox_jobs is None
    result, report = import_v1(v1, check=False)
    assert result.returncode == 1 and "job" in report["missing_tables"]
    case = ImportedCase.objects.get(reference="CAT-AC00-0011")
    with pytest.raises(Refused, match="history_incomplete"):
        mailbox_history.settled(case.application, case.v1_case_id)
    v1.owner.execute(
        sql.SQL("DROP TABLE {}.mailbox_account").format(sql.Identifier(v1.schema))
    )
    result, report = import_v1(v1, check=False)
    assert result.returncode == 1 and "mailbox_account" in report["missing_tables"]
    assert mailbox_history.latest(case.application).data["tables_complete"] is False


def test_mailbox_handover_refuses_late_uncertain_welcome_even_with_original_sent_receipt(
    mailbox, v1
):
    case = ImportedCase.objects.get(application=mailbox.application)
    mailbox_id = account(v1, case.v1_case_id)
    old_digest = review.review_state(mailbox.application)["digest"]
    changed(
        v1,
        "mailbox_account",
        mailbox_id,
        welcome_round=2,
        welcome_sent_at=None,
        welcome_send_started_at=v1.at(100),
    )
    import_v1(v1)
    with pytest.raises(Refused, match="changed_since_shown"):
        confirm(mailbox, expected_digest=old_digest)
    with pytest.raises(Refused, match="legacy_welcome_delivery"):
        confirm(mailbox)
    assert not ProvisioningEvidence.objects.filter(request=mailbox.request).exists()
    assert FakeMailHost.calls == []


def test_mailbox_handover_refuses_running_mismatched_and_unknown_jobs(mailbox, v1):
    case = ImportedCase.objects.get(application=mailbox.application)
    mailbox_id = account(v1, case.v1_case_id)
    delivery = job(v1, case.v1_case_id, mailbox_id, status="running")
    import_v1(v1)
    with pytest.raises(Refused, match="delivery_requires_reconciliation"):
        confirm(mailbox)
    changed(v1, "job", delivery, status="succeeded", case_id="wrong-case")
    import_v1(v1)
    with pytest.raises(Refused, match="delivery_requires_reconciliation"):
        confirm(mailbox)
    changed(v1, "job", delivery, case_id=case.v1_case_id, action_key="future-key")
    import_v1(v1)
    with pytest.raises(Refused, match="delivery_requires_reconciliation"):
        confirm(mailbox)
    assert FakeMailHost.calls == []


def test_mailbox_handover_revalidates_current_address_and_source_during_provider_read(
    mailbox, v1, monkeypatch
):
    case = ImportedCase.objects.get(application=mailbox.application)
    mailbox_id = account(v1, case.v1_case_id)
    changed(v1, "mailbox_account", mailbox_id, username="changed.name")
    import_v1(v1)
    with pytest.raises(Refused, match="identity_changed"):
        confirm(mailbox)
    changed(
        v1,
        "mailbox_account",
        mailbox_id,
        username=mailbox.request.reservation.local_part,
    )
    import_v1(v1)
    read = FakeMailHost.read

    def concurrent_read(host, domain, local):
        found = read(host, domain, local)
        job(v1, case.v1_case_id, mailbox_id, status="running")
        import_v1(v1)
        return found

    monkeypatch.setattr(FakeMailHost, "read", concurrent_read)
    with pytest.raises(Refused, match="changed_since_shown"):
        confirm(mailbox)
    assert not ProvisioningEvidence.objects.filter(request=mailbox.request).exists()
    assert not PendingAction.objects.filter(
        subject_id=mailbox.application.public_ref
    ).exists()


def test_release_handover_requires_settled_source_release_jobs(pending):
    case_id = pending.ids["CAT-RP00-0009"]
    source_db = pending.source
    delivery = job(source_db, case_id, None, kind="case_auto_release", status="running")
    import_v1(source_db)
    with pytest.raises(Refused, match="delivery_requires_reconciliation"):
        prepare(pending)
    changed(source_db, "job", delivery, status="failed", outcome_unknown=True)
    import_v1(source_db)
    with pytest.raises(Refused, match="delivery_requires_reconciliation"):
        prepare(pending)
    # A stopped source's never-attempted job is not replayed by the native handoff.
    changed(
        source_db, "job", delivery, status="queued", outcome_unknown=False, attempts=0
    )
    import_v1(source_db)
    receipt = prepare(pending)
    assert receipt.pk and FakeMailHost.calls == []
    assert (
        PendingAction.objects.get(subject_id=pending.application.public_ref).status
        == "held"
    )


def test_mailbox_case_change_without_a_new_event_requires_reconciliation(mailbox, v1):
    case = ImportedCase.objects.get(application=mailbox.application)
    changed(v1, "onboarding_case", case.v1_case_id, state="suspended")
    import_v1(v1)
    with pytest.raises(Refused, match="case_requires_reconciliation"):
        confirm(mailbox)
    assert FakeMailHost.calls == []
