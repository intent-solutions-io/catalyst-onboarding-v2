"""Bead bgl.9 (034 rows 30 and 36; first-generation decisions 12 and 13, owner YES 2026-10-31): the automated company
countersignature with a single-writer claim, and the automatic release. Synthetic only: the local fake Documenso (its
recipient-token routes model the first generation's countersign calls) and the local fake mail host; `example.test`
addresses; no real provider.
"""

import hashlib
import json
import threading
import types
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from agreements import completion, countersign, provider, services
from agreements.models import AgreementInstance, AgreementTemplateVersion, AgreementType, CountersignClaim
from applications.models import Application, ApplicationEvent
from config import guards
from correspondence.models import StaffItem
from correspondence.staff_items import event, open_item, resolve_item
from provisioning import auto_release, closure
from provisioning import services as provisioning_services
from provisioning.models import ProvisioningRequest
from tests.documenso_fake import TOKEN
from tests.test_agreement_completion import reads_now
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, c, complete, d, ev, g, h, issued, k, of, p2, pv, run_worker, sign_and_settle, tls,
)
from workflow import journal, ledger
from workflow.models import PendingAction

COMPANY = "company.countersigner@example.test"
SIGNATURE = "Synthetic Company Signer"
PDF = b"%PDF-1.7 synthetic placeholder agreement"
SECRETS = ("secret-signing-token", "/sign/", TOKEN)


def company_templates(env):
    """Template version 2 of each type with a company recipient slot (APPROVER at order 2), approved; the fake's
    templates know the slot's role."""
    for key, ref, number, slots in (("nda", "envelope_template_nda_cs", 111, {"SIGNER:1": 7001, "APPROVER:2": 7011}),
                                    ("user_agreement", "envelope_template_ua_cs", 112, {"SIGNER:1": 7002, "APPROVER:2": 7012})):
        env.fake.templates[ref] = {"number": number, "slots": {slot: role.split(":")[0] for role, slot in slots.items()}}
        version = AgreementTemplateVersion.objects.create(
            agreement_type=AgreementType.objects.get(key=key), version=2, provider_template_ref=ref,
            provider_template_number=number, recipient_slots=slots, pdf_sha256=hashlib.sha256(PDF).hexdigest())
        services.approve_template_version(version.pk, env.template_owner, services.template_digest(version))


@pytest.fixture
def cs(pv, settings):
    """`pv` (agreements with custody, the fake mail host, the approver) plus the company recipient and the automated
    countersignature."""
    settings.CATALYST_AGREEMENT_COMPANY_EMAIL = COMPANY
    settings.CATALYST_AGREEMENT_COMPANY_NAME = "Synthetic Company"
    settings.CATALYST_AGREEMENT_COMPANY_ROLE = "APPROVER"
    settings.CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE = SIGNATURE
    settings.CATALYST_AGREEMENT_COUNTERSIGN = "automatic"
    company_templates(pv)
    return pv


def applicant_signs(env, app, key="nda"):
    """The company's signature field exists on the envelope (the template places it); the applicant signs."""
    instance = of(app, key).get()
    env.fake.add_field(instance.envelope_id, 1)
    env.fake.sign(instance.envelope_id, 0)
    return instance


def trpc(env, name):
    return [r for r in env.fake.requests if r["path"] == f"/api/trpc/{name}"]


def countersign_actions():
    return PendingAction.objects.filter(kind=countersign.COUNTERSIGN)


def schedule() -> dict:
    out = StringIO()
    call_command("schedule_automation", stdout=out)
    return json.loads(out.getvalue())


def due_now(kind):
    PendingAction.objects.filter(kind=kind, status="queued").update(due_at=timezone.now())


def journal_entries(kind="agreement_countersign"):
    return [(e.key, e.data.get("phase")) for e in journal.read() if e.kind == kind]


# --- the countersignature ----------------------------------------------------------------------------------------

def test_bgl9_the_company_countersigns_once_after_the_applicant_and_the_read_path_verifies(cs, monkeypatch, caplog):
    app = issued(cs, monkeypatch)
    instance = of(app, "nda").get()
    assert [(r.who, r.role, r.signing_order, r.required) for r in instance.recipients.order_by("signing_order")] == [
        ("applicant", "SIGNER", 1, True), ("staff", "APPROVER", 2, True)]  # P4-D-3: the company at order 2
    assert [(r["role"], r["email"]) for r in cs.fake.envelopes[instance.envelope_id]["recipients"]][1] == ("APPROVER", COMPANY)
    applicant_signs(cs, app)
    reads_now()  # the read shows the applicant signed: the countersignature is queued and runs at once
    claim = CountersignClaim.objects.get()
    assert (claim.envelope_id, claim.state, claim.holder, claim.attempts) == (instance.envelope_id, "signed", "catalyst_v2", 1)
    env = cs.fake.envelopes[instance.envelope_id]
    assert env["status"] == "COMPLETED" and env["_countersigned"] == [COMPANY]
    assert [f["customText"] for f in env["fields"] if f["recipientId"] == env["recipients"][1]["id"]] == [SIGNATURE]
    sign, done = trpc(cs, "envelope.field.sign"), trpc(cs, "recipient.completeDocumentWithToken")
    assert len(sign) == len(done) == 1
    for request in sign + done:  # the recipient token is the credential: never the API key, always the Origin
        assert "Authorization" not in request["headers"] and request["headers"]["Origin"].startswith("https://documenso.example.test:")
        assert TOKEN.encode() not in request["body"]
    key = f"countersign:{instance.public_id}"
    assert journal_entries() == [(key, "begun"), (key, "done")]  # journaled before the call, and once verified
    assert ApplicationEvent.objects.filter(application=app, kind="agreement_countersigned").count() == 1
    reads_now()  # the ordinary read path verifies the completed envelope, never the countersign module
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status == "signing_complete_verified"
    history = json.dumps(list(ApplicationEvent.objects.values("data", "actor_ref"))) + json.dumps(
        list(CountersignClaim.objects.values()), default=str)
    for secret in SECRETS:
        assert secret not in history and secret not in caplog.text


def test_bgl9_a_countersignature_is_verified_by_a_fresh_read_not_by_the_call(cs, monkeypatch):
    app = issued(cs, monkeypatch)
    instance = applicant_signs(cs, app)
    reads, real_read = [], provider.read
    monkeypatch.setattr(provider, "read", lambda envelope_id: reads.append(envelope_id) or real_read(envelope_id))
    monkeypatch.setattr(provider, "countersign", lambda *args: "SIGNED")  # claims success, signs nothing
    with transaction.atomic():
        countersign.enqueue(AgreementInstance.objects.select_related("application").get(pk=instance.pk))
    run_worker()
    assert reads == [instance.envelope_id, instance.envelope_id]  # before the claim, and after the call
    claim = CountersignClaim.objects.get()
    assert (claim.state, claim.last_code) == ("failed", "not_signed_after_countersign")
    assert countersign_actions().get().status == "queued"  # retried later, never recorded as signed
    assert not ApplicationEvent.objects.filter(kind="agreement_countersigned").exists()
    assert cs.fake.envelopes[instance.envelope_id]["status"] == "PENDING"


def test_bgl9_two_workers_one_claim_one_signature(cs, monkeypatch):
    app = issued(cs, monkeypatch)
    instance = applicant_signs(cs, app)
    for n in (1, 2):  # two actions for one envelope (a duplicate the coalescing would never make), two workers at once
        PendingAction.objects.create(kind=countersign.COUNTERSIGN, subject_type="application", subject_id=app.public_ref,
                                     input_ref=str(instance.public_id), idempotency_key=f"countersign_agreement:x:{n}",
                                     max_attempts=4)
    cs.fake.trpc_fault("envelope.field.sign", ("slow", 1.0))  # the first writer is still signing when the second arrives
    registry, start = {countersign.COUNTERSIGN: countersign.CountersignAgreement()}, threading.Barrier(2)

    def work():
        start.wait(10)
        ledger.run_one(registry)

    threads = [cs.committed.thread(work) for _ in range(2)]
    for thread in threads:
        thread.join(30)
    assert len(trpc(cs, "envelope.field.sign")) == 1 and len(trpc(cs, "recipient.completeDocumentWithToken")) == 1
    assert CountersignClaim.objects.count() == 1 and CountersignClaim.objects.get().state == "signed"
    outcomes = sorted(countersign_actions().values_list("status", "last_error"))
    assert outcomes[0] == ("done", "") and outcomes[1][0] == "done"
    assert outcomes[1][1] in ("already_claimed", "claim_signed", "already_signed")
    assert cs.fake.envelopes[instance.envelope_id]["_countersigned"] == [COMPANY]


def test_bgl9_the_claim_is_unique_per_envelope_and_only_for_v2_keys(cs, monkeypatch):
    app = issued(cs, monkeypatch)
    instance = of(app, "nda").get()
    CountersignClaim.objects.create(instance=instance, envelope_id=instance.envelope_id, external_key=instance.external_key,
                                    holder="catalyst_v2")
    with pytest.raises(IntegrityError), transaction.atomic():  # a second consumer cannot claim the same envelope
        CountersignClaim.objects.create(instance=instance, envelope_id=instance.envelope_id,
                                        external_key=instance.external_key, holder="another_writer")
    with pytest.raises(IntegrityError), transaction.atomic():  # a first-generation key is never claimable
        CountersignClaim.objects.create(instance=instance, envelope_id="envelope_legacy", external_key="onb_case_1",
                                        holder="catalyst_v2")
    assert CountersignClaim.objects.count() == 1


def test_bgl9_a_foreign_envelope_is_refused_and_never_touched(cs, monkeypatch):
    app = issued(cs, monkeypatch)
    instance = applicant_signs(cs, app)
    cs.fake.envelopes[instance.envelope_id]["externalId"] = "onb_legacy_case_1"  # not an envelope v2 created
    before = len(cs.fake.requests)
    with pytest.raises(provider.CountersignRefused, match="not_a_v2_envelope"):  # refused before any request
        provider.countersign(instance.envelope_id, "onb_legacy_case_1", COMPANY, "APPROVER", SIGNATURE)
    assert len(cs.fake.requests) == before
    assert countersign.schedule_sweep()
    run_worker()  # the sweep queues it from the database; the countersign reads, sees a foreign key, signs nothing
    assert not trpc(cs, "envelope.field.sign") and not trpc(cs, "recipient.completeDocumentWithToken")
    assert not CountersignClaim.objects.exists()
    item = StaffItem.objects.get(application=app, reason_code=countersign.REFUSED, status="open")
    assert item.dedupe_key == f"countersign:{instance.public_id}:not_a_v2_envelope"
    due_now(countersign.SWEEP)
    run_worker()  # the next sweep leaves a refused agreement to staff: no second item, no second event
    assert StaffItem.objects.filter(reason_code=countersign.REFUSED).count() == 1
    assert ApplicationEvent.objects.filter(application=app, kind="agreement_countersign_refused").count() == 1


def test_bgl9_a_failure_is_retried_and_the_retry_signs_once(cs, monkeypatch, settings):
    app = issued(cs, monkeypatch)
    instance = applicant_signs(cs, app)
    cs.fake.trpc_fault("envelope.field.sign", ("status", 500))
    reads_now()
    claim = CountersignClaim.objects.get()
    assert (claim.state, claim.last_code) == ("failed", "http_500") and claim.first_failure_at is not None
    action = countersign_actions().get()
    assert action.status == "queued" and action.due_at > timezone.now() + timedelta(seconds=500)  # the retry interval
    assert not StaffItem.objects.filter(reason_code=countersign.HANDED_OFF).exists()
    due_now(countersign.COUNTERSIGN)
    run_worker()
    assert CountersignClaim.objects.get().state == "signed"
    assert len(trpc(cs, "envelope.field.sign")) == 2 and len(trpc(cs, "recipient.completeDocumentWithToken")) == 1
    assert cs.fake.envelopes[instance.envelope_id]["_countersigned"] == [COMPANY]


def test_bgl9_after_thirty_minutes_of_failure_the_owner_countersigns_by_hand(cs, monkeypatch, settings):
    settings.CATALYST_AGREEMENT_COUNTERSIGN_ATTEMPTS = 10  # the window, not the attempt count, ends it here
    app = issued(cs, monkeypatch)
    instance = applicant_signs(cs, app)
    cs.fake.trpc_fault("envelope.field.sign", ("status", 500), ("status", 500))
    reads_now()
    assert CountersignClaim.objects.get().state == "failed"
    CountersignClaim.objects.update(first_failure_at=timezone.now() - timedelta(minutes=31))
    due_now(countersign.COUNTERSIGN)
    run_worker()
    claim = CountersignClaim.objects.get()
    assert (claim.state, claim.last_code) == ("handed_off", "http_500")
    assert countersign_actions().get().status == "failed"
    item = StaffItem.objects.get(application=app, reason_code=countersign.HANDED_OFF, status="open")
    assert item.dedupe_key == f"countersign:{instance.public_id}"
    assert ApplicationEvent.objects.filter(application=app, kind="agreement_countersign_handed_off").count() == 1
    assert countersign.schedule_sweep()
    run_worker()  # automation leaves it to the owner: nothing more is queued for it
    assert countersign_actions().count() == 1
    cs.fake.sign(instance.envelope_id, 1)  # the owner countersigns by hand at the provider
    reads_now()
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status == "signing_complete_verified"


def test_bgl9_a_paused_case_is_never_countersigned(cs, monkeypatch):
    app = issued(cs, monkeypatch)
    instance = applicant_signs(cs, app)
    completion._pause(Application.objects.get(pk=app.pk), "synthetic_pause")
    with transaction.atomic():
        countersign.enqueue(AgreementInstance.objects.select_related("application").get(pk=instance.pk))
    run_worker()
    assert countersign_actions().get().status == "queued" and not trpc(cs, "envelope.field.sign")


def test_bgl9_a_lapsed_case_is_never_countersigned_and_the_signature_that_reopens_it_resumes_it(cs, monkeypatch):
    """bgl.9 x bgl.7 (parity integration): a lapsed application is not in `agreements`, so neither the sweep, nor a
    queued countersign, signs for the company; the applicant's signature reopens it on the next read and the
    countersignature follows at once."""
    from applications.models import Stage
    from applications.stages import transition
    from correspondence import lapse

    app = issued(cs, monkeypatch)
    instance = of(app, "nda").get()
    with transaction.atomic():  # as correspondence.lapse does after ten quiet business days
        transition(app.pk, (Stage.AGREEMENTS,), Stage.LAPSED, event_kind=lapse.LAPSED_EVENT,
                   data={"trigger": f"agreement:{instance.public_id}"}, actor_ref="test")
    applicant_signs(cs, app)
    fresh = AgreementInstance.objects.select_related("application").get(pk=instance.pk)
    assert countersign.eligible(fresh) == "not_in_agreements"
    with transaction.atomic():
        assert countersign.enqueue(fresh) is None
    assert list(countersign.candidates()) == []  # the sweep finds nothing
    stale = PendingAction.objects.create(  # one queued before the lapse: it runs, signs nothing, and ends
        kind=countersign.COUNTERSIGN, subject_type="application", subject_id=app.public_ref, input_ref=str(instance.public_id),
        idempotency_key=f"{countersign.COUNTERSIGN}:{instance.public_id}:1", max_attempts=4)
    run_worker()
    assert (PendingAction.objects.get(pk=stale.pk).status, PendingAction.objects.get(pk=stale.pk).last_error) == (
        "done", "not_in_agreements")
    assert not CountersignClaim.objects.exists() and not trpc(cs, "envelope.field.sign")
    reads_now()  # the read sees the applicant's signature: reopened to `agreements`, then countersigned
    [reopened] = ApplicationEvent.objects.filter(application=app, kind=lapse.REOPENED_EVENT)
    assert reopened.data["trigger"] == f"signature:{instance.public_id}"
    claim = CountersignClaim.objects.get()
    assert claim.state == "signed" and len(trpc(cs, "recipient.completeDocumentWithToken")) == 1
    assert cs.fake.envelopes[instance.envelope_id]["status"] == "COMPLETED"


def test_bgl9_both_modes_off_by_default_leave_todays_behaviour(pv, monkeypatch, settings):
    import config.settings as defaults

    assert (defaults.CATALYST_AGREEMENT_COUNTERSIGN, defaults.CATALYST_RELEASE_MODE) == ("manual", "owner")
    assert defaults.CATALYST_AGREEMENT_COMPANY_EMAIL == "" and defaults.CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE == ""
    company_templates(pv)  # even with a company slot, no company recipient while its address is unset
    app = complete(pv, monkeypatch)
    for instance in AgreementInstance.objects.filter(application=app):
        assert list(instance.recipients.values_list("who", flat=True)) == ["applicant"]
    assert not countersign_actions().exists() and not PendingAction.objects.filter(kind=auto_release.AUTO_RELEASE).exists()
    assert PendingAction.objects.get(kind="provision").status == "held"  # the owner's activate_provisioning releases it
    assert schedule() == {"auto_release_queued": 0, "countersign_sweep": "off", "release_mode": "owner"}
    assert countersign.schedule_sweep()
    run_worker()  # a sweep left from an earlier switch ends its chain under "manual"
    assert PendingAction.objects.filter(kind=countersign.SWEEP).count() == 1
    assert not ProvisioningRequest.objects.exists()


def test_bgl9_under_manual_the_company_recipient_waits_for_the_owner(cs, monkeypatch, settings):
    settings.CATALYST_AGREEMENT_COUNTERSIGN = "manual"
    app = issued(cs, monkeypatch)
    instance = applicant_signs(cs, app)
    reads_now()
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status == "partially_signed"
    assert not countersign_actions().exists() and not trpc(cs, "envelope.field.sign")


def test_bgl9_the_new_settings_are_guarded():
    def problems(**values):
        base = {"CATALYST_ENV": "test", "CATALYST_AGREEMENT_COUNTERSIGN": "manual", "CATALYST_RELEASE_MODE": "owner",
                "CATALYST_AGREEMENT_COMPANY_ROLE": "APPROVER", "CATALYST_AGREEMENT_COMPANY_EMAIL": "",
                "CATALYST_AGREEMENT_COMPANY_NAME": "", "CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE": ""}
        environ = values.pop("environ", {})
        return guards.automation_problems(types.SimpleNamespace(**{**base, **values}), environ)

    assert problems() == []
    assert problems(CATALYST_AGREEMENT_COUNTERSIGN="automatic", CATALYST_AGREEMENT_COMPANY_EMAIL=COMPANY,
                    CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE=SIGNATURE) == []
    for env in ("production", "development"):  # provider identity only in test and staging
        found = problems(CATALYST_ENV=env, CATALYST_AGREEMENT_COMPANY_EMAIL=COMPANY, CATALYST_AGREEMENT_COMPANY_NAME="X",
                         CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE=SIGNATURE)
        assert sum("allowed only in the test and staging environments" in p for p in found) == 3, found
    assert any(".test domain" in p for p in problems(CATALYST_ENV="staging", CATALYST_AGREEMENT_COMPANY_EMAIL="owner@example.com"))
    assert any("needs CATALYST_AGREEMENT_COMPANY_EMAIL" in p for p in problems(CATALYST_AGREEMENT_COUNTERSIGN="automatic"))
    assert any("'manual' or 'automatic'" in p for p in problems(CATALYST_AGREEMENT_COUNTERSIGN="sometimes"))
    assert any("'owner' or 'automatic'" in p for p in problems(CATALYST_RELEASE_MODE="always"))
    assert any("'APPROVER' or 'SIGNER'" in p for p in problems(CATALYST_AGREEMENT_COMPANY_ROLE="CC"))
    for name in ("CATALYST_AGREEMENT_COUNTERSIGN", "CATALYST_RELEASE_MODE", "CATALYST_AGREEMENT_COMPANY_EMAIL"):
        assert f"{name} may not be set from the environment" in problems(environ={name: "x"})
    assert guards.all_problems.__code__.co_names.count("automation_problems") == 1  # wired into the start-up guards


# --- the automatic release ----------------------------------------------------------------------------------------

def handoff_of(app):
    return PendingAction.objects.get(kind="provision", subject_id=app.public_ref)


def test_bgl9_the_release_runs_once_without_a_person_and_queues_the_welcome(pv, monkeypatch, settings):
    app = complete(pv, monkeypatch)  # held under the owner mode
    settings.CATALYST_RELEASE_MODE = "automatic"
    assert schedule() == {"auto_release_queued": 1, "countersign_sweep": "off", "release_mode": "automatic"}
    assert schedule()["auto_release_queued"] == 0  # one per hand-off
    run_worker()
    request = ProvisioningRequest.objects.get(application=app)
    assert request.approved_by == "auto-release" and request.reservation.basis == "naming_rule"
    assert request.status == "setup_pending"  # created, verified, and the credential setup opened
    assert PendingAction.objects.filter(kind="provision_invite", subject_id=app.public_ref).exists()  # the welcome step
    released = ApplicationEvent.objects.get(application=app, kind="provisioning_released")
    assert released.actor_ref == "auto-release" and released.data["approval_ref"] == auto_release.APPROVAL_REF
    approved = ApplicationEvent.objects.get(application=app, kind="provisioning_approved")
    assert approved.actor_ref == "auto-release" and approved.data["by"] == "automatic"
    assert handoff_of(app).status == "done"
    PendingAction.objects.filter(kind=auto_release.AUTO_RELEASE).update(status="queued", due_at=timezone.now())
    run_worker()  # a repeated run releases nothing more
    assert ProvisioningRequest.objects.filter(application=app).count() == 1
    assert ApplicationEvent.objects.filter(application=app, kind="provisioning_released").count() == 1


def test_bgl9_the_hand_off_queues_the_release_itself(pv, monkeypatch, settings):
    settings.CATALYST_RELEASE_MODE = "automatic"
    app = issued(pv, monkeypatch)
    sign_and_settle(pv, app, "nda")
    sign_and_settle(pv, app, "user_agreement")
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    assert ProvisioningRequest.objects.get(application=app).approved_by == "auto-release"


def _paused(app, monkeypatch):
    completion._pause(Application.objects.get(pk=app.pk), "synthetic_pause")


def _on_hold(app, monkeypatch):
    event(app, completion.STOPPED_EVENT, {"by": "test"})


def _closed(app, monkeypatch):
    with transaction.atomic():
        locked = Application.objects.select_for_update(of=("self",)).get(pk=app.pk)
        closure.close_locked(locked, "closed", "Synthetic closure for the test", "test",
                             ApplicationEvent.ActorType.SYSTEM)


def _staff_item(app, monkeypatch):
    open_item("synthetic_review", f"synthetic:{app.public_ref}", application=app)


def _address(app, monkeypatch):
    monkeypatch.setattr(auto_release, "verified_address", lambda application: None)


def _details(app, monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "CATALYST_AGREEMENT_REQUIRED_DETAILS", {"user_agreement": ["synthetic_field"]})


@pytest.mark.parametrize(("condition", "reason"), [
    (_paused, "paused"), (_on_hold, "on_hold"), (_closed, "closed"), (_staff_item, "staff_item_open"),
    (_address, "address_not_verified"), (_details, "details_needed")])
def test_bgl9_each_blocking_condition_refuses_once_with_one_staff_item(pv, monkeypatch, settings, condition, reason):
    app = complete(pv, monkeypatch)
    settings.CATALYST_RELEASE_MODE = "automatic"
    assert schedule()["auto_release_queued"] == 1  # queued, not run yet
    condition(app, monkeypatch)
    run_worker()
    for _ in range(2):  # checked again later: still refused, still one record
        assert not ProvisioningRequest.objects.filter(application=app).exists()
        refusals = StaffItem.objects.filter(application=app, reason_code=auto_release.ITEM, status="open")
        assert list(refusals.values_list("dedupe_key", flat=True)) == [f"auto_release:{app.public_ref}:{reason}"]
        assert list(ApplicationEvent.objects.filter(application=app, kind="provisioning_auto_release_refused")
                    .values_list("data__reason", flat=True)) == [reason]
        due_now(auto_release.AUTO_RELEASE)
        run_worker()
    action = PendingAction.objects.get(kind=auto_release.AUTO_RELEASE)
    assert action.status == ("done" if reason == "closed" else "queued")  # a closed case is never checked again


def test_bgl9_a_resolved_condition_releases_on_the_next_check(pv, monkeypatch, settings):
    app = complete(pv, monkeypatch)
    settings.CATALYST_RELEASE_MODE = "automatic"
    schedule()
    blocker = open_item("synthetic_review", f"synthetic:{app.public_ref}", application=app)
    run_worker()
    assert not ProvisioningRequest.objects.exists()
    resolve_item(blocker, code="done", actor_ref="test")
    due_now(auto_release.AUTO_RELEASE)
    run_worker()
    assert ProvisioningRequest.objects.get(application=app).approved_by == "auto-release"
    assert not StaffItem.objects.filter(application=app, reason_code=auto_release.ITEM, status="open").exists()


def test_bgl9_a_reviewed_address_exception_waits_for_the_named_approver(pv, monkeypatch, settings):
    app = complete(pv, monkeypatch)
    provisioning_services.reserve_exception(app.pk, "ada.preferred", pv.approver, "Preferred professional name, reviewed")
    settings.CATALYST_RELEASE_MODE = "automatic"
    schedule()
    run_worker()
    request = ProvisioningRequest.objects.get(application=app)
    assert request.status == "awaiting_approval" and request.approved_by == ""  # released, not approved by automation
    assert StaffItem.objects.filter(application=app, reason_code=auto_release.ITEM, status="open",
                                    dedupe_key=f"auto_release:{app.public_ref}:address_needs_approver").count() == 1


# --- both together ---------------------------------------------------------------------------------------------------

def test_bgl9_end_to_end_countersigned_agreements_release_without_a_person(cs, monkeypatch, settings):
    settings.CATALYST_RELEASE_MODE = "automatic"
    app = issued(cs, monkeypatch)
    for key in ("nda", "user_agreement"):
        applicant_signs(cs, app, key)
        reads_now()  # countersigned
        reads_now()  # verified, stored, and the next step taken
    assert list(CountersignClaim.objects.values_list("state", flat=True)) == ["signed", "signed"]
    app = Application.objects.get(pk=app.pk)
    assert app.stage == "provisioning"
    assert ProvisioningRequest.objects.get(application=app).approved_by == "auto-release"
    assert PendingAction.objects.filter(kind="provision_invite", subject_id=app.public_ref).exists()
    assert not ApplicationEvent.objects.filter(application=app, actor_type="staff", kind__in=(
        "agreement_countersigned", "provisioning_released", "provisioning_approved")).exists()  # no person acted
