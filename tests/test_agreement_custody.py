"""P4 task 4B.3: custody, retrieval, required details, the staff agreement screen and the held P5 hand-off (021
sections 4 step 6 to 8, 7, 8, 9; D-40). TEST-P4-04, 05, 07, 17, 19, 21, 27.

The default gate (signing AND custody, P4-D-6) is used throughout: no signing-only override.
"""

import os
import uuid
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from agreements import completion, custody, services, storage
from agreements.models import AgreementDetailsVersion, AgreementInstance, DocumentAccess, StoredDocument
from applications.models import Application
from correspondence.models import StaffItem
from tests.test_agreement_completion import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, activate, approve, c, d, ev, g, grant, h, issued, nda, p2, reads_now, run_worker, tls,
)
from tests.test_outbound import staff
from workflow.models import PendingAction


@pytest.fixture
def k(h, settings, tmp_path):
    """`h` plus isolated custody storage outside the repository, and the 4B.3 roles granted to named synthetic
    people: a reader, an operator and the decision-maker."""
    settings.CATALYST_AGREEMENT_STORAGE_DIR = str(tmp_path / "custody")
    for perm in ("retrieve_agreement_document", "operate_agreements", "confirm_required_details",
                 "resolve_agreement_integrity"):
        grant(h, h.agreement_decider, perm)
    h.reader = grant(h, staff(h, "agreement-reader"), "view_agreementinstance")
    h.operator = grant(h, staff(h, "agreement-operator"), "operate_agreements")
    h.storage = Path(settings.CATALYST_AGREEMENT_STORAGE_DIR)
    return h


def items(app, reason):
    return StaffItem.objects.filter(application=app, reason_code=reason, status="open")


def of(app, key):
    return AgreementInstance.objects.filter(application=app, agreement_type__key=key).exclude(
        issue_status__in=("cancelled", "superseded"))


def sign_and_settle(k, app, key):
    instance = of(app, key).get()
    k.fake.sign(instance.envelope_id)
    reads_now()
    run_worker()
    return AgreementInstance.objects.get(pk=instance.pk)


# --- TEST-P4-04, 19: the default-gate journey and the held hand-off ------------------------------------------------

def test_p4_04_19_the_default_gate_journey_ends_in_exactly_one_held_hand_off(k, monkeypatch):
    app = issued(k, monkeypatch)
    nda_instance = sign_and_settle(k, app, "nda")
    assert (nda_instance.signing_status, nda_instance.custody_status) == ("signing_complete_verified", "stored_verified")
    document = StoredDocument.objects.get(instance=nda_instance)
    path = k.storage / document.storage_key
    assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
    assert storage.sha256(path.read_bytes()) == document.sha256 and document.envelope_id == nda_instance.envelope_id
    assert not str(path).startswith(str(Path(__file__).resolve().parent.parent))  # outside the repository
    events = list(app.events.order_by("id").values_list("kind", flat=True))
    assert events.index("agreement_custody_verified") < max(i for i, e in enumerate(events) if e == "agreement_instance_created")
    ua = sign_and_settle(k, app, "user_agreement")
    assert ua.custody_status == "stored_verified"
    app.refresh_from_db()
    assert app.stage == "agreements_complete"
    handoff = PendingAction.objects.get(kind="provision")
    assert handoff.status == "held" and handoff.input_ref.startswith("agreements:")
    complete = app.events.get(kind="agreements_complete")
    refs = complete.data["prerequisites"]
    assert set(refs) == {"nda", "user_agreement"}
    for key in refs:  # the exact references: the instance and its stored documents
        live = of(app, key).get()
        assert refs[key]["instance"] == str(live.public_id)
        assert refs[key]["documents"] == [str(d) for d in live.documents.values_list("public_id", flat=True)]
    completion.enqueue_advance(Application.objects.get(pk=app.pk))  # a duplicate or stale callback
    run_worker()
    assert PendingAction.objects.filter(kind="provision").count() == 1
    from django.conf import settings
    assert "provision" not in settings.CATALYST_ACTION_HANDLERS  # nothing runs it


# --- TEST-P4-05: required details ----------------------------------------------------------------------------------

def test_p4_05_the_user_agreement_waits_for_confirmed_required_details(k, monkeypatch, settings):
    settings.CATALYST_AGREEMENT_REQUIRED_DETAILS = {"user_agreement": ["mailing_country"]}  # synthetic field
    app = issued(k, monkeypatch)
    sign_and_settle(k, app, "nda")
    assert not of(app, "user_agreement").exists() and items(app, completion.DETAILS_NEEDED).count() == 1
    with pytest.raises(services.PermissionDenied):
        services.record_required_details(app.pk, "user_agreement", {"mailing_country": "Exampleland"}, k.reader)
    with pytest.raises(services.Refused, match="fields_mismatch"):
        services.record_required_details(app.pk, "user_agreement", {"other": "x"}, k.agreement_decider)
    draft = services.record_required_details(app.pk, "user_agreement", {"mailing_country": "Exampleland"},
                                             k.agreement_decider)
    run_worker()
    assert not of(app, "user_agreement").exists()  # a draft is not confirmed
    with pytest.raises(services.Refused, match="changed_since_shown"):
        services.confirm_required_details(draft.pk, k.agreement_decider, "0" * 64)
    services.confirm_required_details(draft.pk, k.agreement_decider, draft.values_sha256)
    assert not items(app, completion.DETAILS_NEEDED).exists()
    run_worker()
    assert of(app, "user_agreement").count() == 1
    owner = k.committed.connect("owner", autocommit=True)
    from psycopg import errors
    with pytest.raises(errors.InsufficientPrivilege):  # a confirmed version is final for every role
        owner.execute("UPDATE agreements_agreementdetailsversion SET values = '{}' WHERE id = %s", [draft.pk])
    assert AgreementDetailsVersion.objects.get(pk=draft.pk).status == "confirmed"


# --- TEST-P4-07: custody failure, corruption and interruption ----------------------------------------------------

def test_p4_07_a_custody_outage_leaves_signing_verified_and_blocks_only_progression(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    k.fake.fault("GET /envelope/item/", ("status", 503), ("status", 503), ("status", 503))
    k.fake.sign(instance.envelope_id)
    reads_now()
    run_worker()
    instance.refresh_from_db()
    assert (instance.signing_status, instance.custody_status) == ("signing_complete_verified", "failed_needs_staff")
    assert items(app, custody.CUSTODY_FAILED).count() == 1
    assert not of(app, "user_agreement").exists() and len(k.fake.calls("POST", "/envelope/use")) == 1  # nothing reissued
    with pytest.raises(services.PermissionDenied):
        services.retry_custody(instance.pk, k.reader)
    services.retry_custody(instance.pk, k.operator)
    run_worker()
    assert AgreementInstance.objects.get(pk=instance.pk).custody_status == "stored_verified"
    assert of(app, "user_agreement").count() == 1


def test_p4_07_a_non_pdf_is_never_stored(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    k.fake.download = (200, "text/html", b"<html>not a pdf</html>")
    k.fake.sign(instance.envelope_id)
    reads_now()
    run_worker()
    assert not StoredDocument.objects.exists() and items(app, custody.CUSTODY_FAILED).count() == 1


def test_p4_07_an_interruption_between_the_file_and_the_record_leaves_one_authoritative_copy(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    real, calls = custody.StoreAgreement._record, {"n": 0}

    def record(self, *args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("interrupted after the file was written")
        return real(self, *args)
    monkeypatch.setattr(custody.StoreAgreement, "_record", record)
    k.fake.sign(instance.envelope_id)
    reads_now()
    run_worker()
    documents = StoredDocument.objects.filter(instance=instance)
    assert documents.count() == 1  # one record, never a silent overwrite
    files = sorted(p.name for p in k.storage.iterdir())
    assert len(files) == 2 and documents.get().storage_key in files  # the first write stays unreferenced, never served


# --- TEST-P4-17, 27: retrieval -------------------------------------------------------------------------------------

def stored(k, monkeypatch):
    app = issued(k, monkeypatch)
    sign_and_settle(k, app, "nda")
    return app, StoredDocument.objects.get()


def test_p4_17_27_retrieval_is_audited_before_any_byte_and_served_as_an_attachment(k, monkeypatch):
    app, document = stored(k, monkeypatch)
    probe = k.committed.connect("owner", autocommit=True)
    real = storage.read

    def read(*args):  # by the time the bytes are read, the access record is committed
        assert probe.execute("SELECT count(*) FROM agreements_documentaccess WHERE outcome = 'granted'").fetchone()[0] == 1
        return real(*args)
    monkeypatch.setattr(storage, "read", read)
    client = Client(enforce_csrf_checks=False)
    client.force_login(k.agreement_decider)
    response = client.post(reverse("agreements_staff:retrieve", args=[document.public_id]), {"note": "Counsel review copy"})
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response["X-Content-Type-Options"] == "nosniff" and "no-store" in response["Cache-Control"]
    assert response["Content-Disposition"].startswith("attachment;")
    assert storage.sha256(response.content) == document.sha256
    access = DocumentAccess.objects.get(outcome="granted")
    assert access.reason == "Counsel review copy" and access.actor_ref == f"user:{k.agreement_decider.pk}"


def test_p4_27_denied_and_missing_look_the_same_and_are_both_recorded(k, monkeypatch):
    app, document = stored(k, monkeypatch)
    for user, ref in ((k.reader, document.public_id), (k.agreement_decider, "00000000-0000-0000-0000-000000000000")):
        client = Client()
        client.force_login(user)
        response = client.post(reverse("agreements_staff:retrieve", args=[ref]), {"note": "Counsel review copy"})
        assert response.status_code == 404 and b"%PDF" not in response.content
    denied = list(DocumentAccess.objects.filter(outcome="denied").values_list("requested_ref", flat=True))
    assert sorted(denied) == sorted([str(document.public_id), "00000000-0000-0000-0000-000000000000"])
    assert not DocumentAccess.objects.filter(outcome="granted").exists()


def test_p4_27_an_audit_failure_releases_nothing(k, monkeypatch):
    app, document = stored(k, monkeypatch)
    read_calls = []
    monkeypatch.setattr(storage, "read", lambda *a: read_calls.append(1) or b"%PDF")
    real_create = DocumentAccess.objects.create

    def create(**kwargs):
        if kwargs.get("outcome") == "granted":
            raise RuntimeError("audit store unavailable")
        return real_create(**kwargs)
    monkeypatch.setattr(DocumentAccess.objects, "create", create)
    with pytest.raises(RuntimeError):
        services.retrieve_document(str(document.public_id), k.agreement_decider, "Counsel review copy")
    assert not read_calls


@pytest.mark.parametrize("tamper", ["bytes", "symlink", "mode"])
def test_p4_27_corruption_or_an_unsafe_file_refuses_and_opens_a_staff_item(k, monkeypatch, tmp_path, tamper):
    app, document = stored(k, monkeypatch)
    path = k.storage / document.storage_key
    if tamper == "bytes":
        path.write_bytes(path.read_bytes()[:-1] + b"X")
    elif tamper == "symlink":
        other = tmp_path / "elsewhere.pdf"
        other.write_bytes(path.read_bytes())
        path.unlink()
        os.symlink(other, path)
    else:
        path.chmod(0o644)
    with pytest.raises(services.Refused, match="document_integrity_failed"):
        services.retrieve_document(str(document.public_id), k.agreement_decider, "Counsel review copy")
    assert DocumentAccess.objects.filter(outcome="refused_integrity").count() == 1
    assert items(app, custody.CUSTODY_CORRUPTED).count() == 1
    assert AgreementInstance.objects.get(pk=document.instance_id).custody_status == "failed_needs_staff"


def test_p4_04_storage_refuses_an_unsafe_directory_and_a_repository_location(k, settings, tmp_path):
    from config import guards

    unsafe = tmp_path / "open"
    unsafe.mkdir(mode=0o755)
    unsafe.chmod(0o755)
    settings.CATALYST_AGREEMENT_STORAGE_DIR = str(unsafe)
    with pytest.raises(storage.StorageError, match="storage_directory_unsafe"):
        storage.write(b"%PDF-1.7 x")

    class Test:
        CATALYST_ENV = "test"
        CATALYST_AGREEMENT_STORAGE_DIR = str(Path(__file__).resolve().parent.parent / "custody")
    assert any("outside the repository" in p for p in guards.agreement_problems(Test, {}))
    settings.CATALYST_AGREEMENT_STORAGE_DIR = str(k.storage)
    with pytest.raises(storage.StorageError, match="storage_key_invalid"):
        storage.read("../../etc/passwd", "x", 1)


# --- TEST-P4-21: the staff screen ------------------------------------------------------------------------------------

def page(app):
    return reverse("agreements_staff:agreements", args=[app.public_ref])


def test_p4_21_the_screen_shows_three_statuses_and_enforces_permissions(k, monkeypatch):
    app = issued(k, monkeypatch)
    Application.objects.filter(pk=app.pk).update(display_name="<script>alert(1)</script> Ada")
    anonymous = Client().get(page(app))
    assert anonymous.status_code == 302 and "login" in anonymous["Location"]
    for user, expected in ((k.reader, 200), (staff(k, "no-agreement-perms"), 403),
                           (staff(k, "root-agreements", superuser=True), 403)):
        client = Client()
        client.force_login(user)
        assert client.get(page(app)).status_code == expected
    client = Client()
    client.force_login(k.reader)
    html = client.get(page(app)).content.decode()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html  # escaped
    for label in ("Issue", "Signing", "Custody", "sent to sign", "not signed", "not due"):
        assert label in html
    assert "Cancel at the provider" not in html  # a reader sees no actions
    assert " checked" not in html  # no consequential choice is preselected


def test_p4_21_actions_need_csrf_their_permission_and_keep_what_was_typed(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    act = reverse("agreements_staff:act", args=[app.public_ref])
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(k.agreement_decider)
    assert strict.post(act, {"action": "cancel", "instance": instance.public_id}).status_code == 403  # no CSRF token
    operator = Client()
    operator.force_login(k.operator)
    refused = operator.post(act, {"action": "cancel", "instance": instance.public_id})
    assert refused.status_code == 409 and b"not_permitted" in refused.content
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "issued"
    decider = Client()
    decider.force_login(k.agreement_decider)
    kept = decider.post(act, {"action": "stop", "reason": "bogus"})
    assert kept.status_code == 409 and b"unknown_reason" in kept.content
    done = decider.post(act, {"action": "cancel", "instance": instance.public_id})
    assert done.status_code == 302
    run_worker()
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "cancelled"


def test_p4_21_a_refused_integrity_disposition_keeps_the_typed_reason(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    k.fake.sign(instance.envelope_id)
    reads_now()
    run_worker()
    k.fake.envelopes[instance.envelope_id]["recipients"].append(
        {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
    completion.enqueue_read(AgreementInstance.objects.get(pk=instance.pk))
    reads_now()
    client = Client()
    client.force_login(k.agreement_decider)
    response = client.post(reverse("agreements_staff:act", args=[app.public_ref]), {
        "action": "resolve", "instance": str(instance.public_id), "disposition": "continue",
        "note": "Checked the provider view twice", "digest": "stale"})
    html = response.content.decode()
    assert response.status_code == 409 and "changed_since_shown" in html
    assert 'value="Checked the provider view twice"' in html and 'value="continue" required checked' in html


# --- PR #43 review regressions --------------------------------------------------------------------------------------

def test_review_a_changed_envelope_during_custody_fails_custody_and_stores_nothing(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    k.fake.sign(instance.envelope_id)
    real = custody.provider.read
    calls = {"n": 0}

    def read(envelope_id):
        env = real(envelope_id)
        calls["n"] += 1
        if calls["n"] >= 3:  # the second custody read, after the downloads: someone was added meanwhile
            import dataclasses
            extra = custody.provider.Recipient("stranger@example.test", "SIGNER", 2, "SIGNED")
            return dataclasses.replace(env, recipients=env.recipients + (extra,))
        return env
    monkeypatch.setattr(custody.provider, "read", read)
    reads_now()
    run_worker()
    assert not StoredDocument.objects.exists()
    assert AgreementInstance.objects.get(pk=instance.pk).custody_status in ("failed_retry_pending", "failed_needs_staff")


def test_review_downloads_run_outside_any_transaction_and_reads_open_the_file_once(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    real_download = custody.provider.download

    def download(item):
        from django.db import connection
        assert not connection.in_atomic_block
        return real_download(item)
    monkeypatch.setattr(custody.provider, "download", download)
    k.fake.sign(instance.envelope_id)
    reads_now()
    run_worker()
    document = StoredDocument.objects.get()
    opens = []
    real_open = os.open
    monkeypatch.setattr(storage.os, "open", lambda path, *a, **kw: opens.append(path) or real_open(path, *a, **kw))
    data = storage.read(document.storage_key, document.sha256, document.size)
    assert opens.count(document.storage_key) == 1 and storage.sha256(data) == document.sha256


def test_review_a_stored_copy_is_never_replaced_by_a_retry_and_a_collision_goes_to_staff(k, monkeypatch):
    app, document = stored(k, monkeypatch)
    path = k.storage / document.storage_key
    path.write_bytes(path.read_bytes()[:-1] + b"X")
    with pytest.raises(services.Refused, match="document_integrity_failed"):
        services.retrieve_document(str(document.public_id), k.agreement_decider, "Counsel review copy")
    with pytest.raises(services.Refused, match="stored_copy_exists"):  # replacing it is the owner's POL-09/10 call
        services.retry_custody(document.instance_id, k.operator)
    # A store run that meets an existing record never ends in a silent "pending".
    instance = AgreementInstance.objects.get(pk=document.instance_id)
    k.committed.connect("app", autocommit=True).execute(
        "UPDATE agreements_agreementinstance SET custody_status = 'pending' WHERE id = %s", [instance.pk])
    from django.db import transaction
    with transaction.atomic():
        custody.enqueue_store(instance)
    run_worker()
    instance.refresh_from_db()
    assert instance.custody_status == "failed_needs_staff" and items(app, custody.CUSTODY_FAILED).count() == 1


def test_review_unavailable_storage_refuses_without_blaming_the_document(k, monkeypatch, settings):
    app, document = stored(k, monkeypatch)
    settings.CATALYST_AGREEMENT_STORAGE_DIR = "/proc/catalyst-no-storage"
    with pytest.raises(services.Refused, match="storage_unavailable"):
        services.retrieve_document(str(document.public_id), k.agreement_decider, "Counsel review copy")
    assert AgreementInstance.objects.get(pk=document.instance_id).custody_status == "stored_verified"
    assert not items(app, custody.CUSTODY_CORRUPTED).exists()


def test_review_retrieval_refuses_inside_a_transaction(k, monkeypatch):
    app, document = stored(k, monkeypatch)
    from django.db import transaction
    with pytest.raises(RuntimeError, match="outside a transaction"), transaction.atomic():
        services.retrieve_document(str(document.public_id), k.agreement_decider, "Counsel review copy")


def test_review_outsiders_get_the_same_404_and_add_no_audit_rows(k, monkeypatch):
    app, document = stored(k, monkeypatch)
    from django.contrib.auth import get_user_model
    outsider = get_user_model().objects.get(pk=staff(k, "not-staff").pk)
    k.committed.connect("owner", autocommit=True).execute("UPDATE accounts_user SET is_staff = false WHERE id = %s",
                                                          [outsider.pk])
    url = reverse("agreements_staff:retrieve", args=[document.public_id])
    anonymous = Client().post(url, {"note": "Counsel review copy"})
    other = Client()
    other.force_login(get_user_model().objects.get(pk=outsider.pk))
    non_staff = other.post(url, {"note": "Counsel review copy"})
    assert non_staff.status_code == 404 and b"%PDF" not in anonymous.content + non_staff.content
    # 6B.9: every anonymous request under /staff/ goes to the login page, so a document that exists and one that does
    # not answer an outsider identically.
    missing = Client().post(reverse("agreements_staff:retrieve", args=[uuid.uuid4()]), {"note": "Counsel review copy"})
    assert anonymous.status_code == missing.status_code == 302
    assert anonymous["Location"].split("?")[0] == missing["Location"].split("?")[0] == "/staff/login/"
    assert not DocumentAccess.objects.exists()


def test_review_an_nda_that_needs_details_starts_once_they_are_confirmed(k, monkeypatch, settings):
    settings.CATALYST_AGREEMENT_REQUIRED_DETAILS = {"nda": ["legal_name_check"]}
    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    run_worker()
    assert not AgreementInstance.objects.filter(application=app).exists()
    assert items(app, completion.DETAILS_NEEDED).count() == 1
    assert PendingAction.objects.get(kind="issue_nda").status == "held"
    draft = services.record_required_details(app.pk, "nda", {"legal_name_check": "Ada Example"}, k.agreement_decider)
    services.confirm_required_details(draft.pk, k.agreement_decider, draft.values_sha256)
    assert not items(app, completion.DETAILS_NEEDED).exists()  # resolved by the confirmation
    run_worker()
    assert PendingAction.objects.get(kind="issue_nda").status == "held"  # only the owner's activation releases it
    activate()
    run_worker()
    assert of(app, "nda").get().issue_status == "issued"


def test_review_malformed_identifiers_are_refused_not_a_server_error(k, monkeypatch):
    app = issued(k, monkeypatch)
    client = Client()
    client.force_login(k.agreement_decider)
    act = reverse("agreements_staff:act", args=[app.public_ref])
    for data in ({"action": "cancel", "instance": "not-a-uuid"}, {"action": "rearm", "attempt": "x"},
                 {"action": "confirm_details", "details": "x"}, {"action": "record_details", "type": "nope"}):
        assert client.post(act, data).status_code == 409, data


def test_review_no_consequential_choice_is_preselected_for_a_decision_maker(k, monkeypatch, settings):
    settings.CATALYST_AGREEMENT_REQUIRED_DETAILS = {"user_agreement": ["mailing_country"]}
    app = issued(k, monkeypatch)
    instance = of(app, "nda").get()
    k.fake.sign(instance.envelope_id)
    reads_now()
    run_worker()
    k.fake.envelopes[instance.envelope_id]["recipients"].append(
        {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
    completion.enqueue_read(AgreementInstance.objects.get(pk=instance.pk))
    reads_now()
    client = Client()
    client.force_login(k.agreement_decider)
    html = client.get(reverse("agreements_staff:agreements", args=[app.public_ref])).content.decode()
    for form in ("Disposition", "Stop every unfinished agreement", "Details the user_agreement needs"):
        assert form in html
    assert " checked" not in html

