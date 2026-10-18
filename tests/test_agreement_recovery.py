"""P4 recovery corrections and the owner's decisions of 2026-10-18 (bead catalyst-v2-hdg.6; D-41 to D-44).

Each test pins a correction or a decision so that reverting it fails:
- **hdg.6 items:** the cancel_uncertain remedy, reissue refusals, nested webhook bodies, advance exhaustion, false
  completion hints, hints on unissued instances, lost completions of closed instances, and the minimum interval
  after a running read.
- **D-41:** the provider's cancellation email is suppressed, and provider email is inventoried apart from
  Catalyst's.
- **D-42:** a hold cancels unfinished envelopes, a resume reissues new instances only, and reissue needs a
  decision-maker.
- **D-43:** an agreement-integrity hold blocks reliance until a permissioned, reasoned, state-bound resolution.
- **D-44:** the orphan watch ends visibly and can be re-armed a bounded number of times; database protections cover
  the new columns.
"""

import json

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from psycopg import errors

from agreements import completion, handlers, provider, services
from agreements.models import AgreementInstance, EnvelopeAttempt
from applications.models import Application
from correspondence.models import StaffItem
from tests.test_agreement_completion import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, activate, approve, c, d, ev, g, grant, h, issued, nda, p2, post, reads_now, reset_gate,
    run_worker, signing_gate, tls,
)
from tests.test_outbound import staff
from workflow import ledger
from workflow.models import PendingAction


def items(app, reason):
    return StaffItem.objects.filter(application=app, reason_code=reason, status="open")


def instances(app, key="nda"):
    return AgreementInstance.objects.filter(application=app, agreement_type__key=key).order_by("id")


@pytest.fixture
def r(h):
    grant(h, h.agreement_decider, "resolve_agreement_integrity")
    return h


# --- hdg.6 corrections -----------------------------------------------------------------------------------------

def test_hdg6_cancel_uncertain_is_remedied_by_a_new_reconciled_cancel(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    r.fake.fault("POST /envelope/cancel", ("drop_before",))  # sent, never processed: unknown
    services.cancel_agreement(instance.pk, r.agreement_decider)
    run_worker()
    instance.refresh_from_db()
    assert instance.issue_status == "cancel_uncertain" and items(app, handlers.CANCEL_UNKNOWN).count() == 1
    services.cancel_agreement(instance.pk, r.agreement_decider)  # the remedy, once reconciliation has ended
    run_worker()
    instance.refresh_from_db()
    assert (instance.issue_status, instance.signing_status) == ("cancelled", "cancelled")
    assert not items(app, handlers.CANCEL_UNKNOWN).exists()
    assert r.fake.envelopes[instance.envelope_id]["status"] == "CANCELLED"
    assert set(instance.attempts.filter(step="cancel").values_list("outcome", flat=True)) == {"decided_not_sent", "succeeded"}
    assert not [m for m in r.fake.emails if m["kind"] == "cancellation"]  # D-41


def test_hdg6_reissue_refuses_a_superseded_instance_and_reports_an_unverified_contact(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    r.fake.reject(instance.envelope_id)
    reads_now()
    with monkeypatch.context() as m:
        m.setattr(handlers, "verified_address", lambda application: None)
        with pytest.raises(services.Refused, match="contact_not_verified"):  # a Refused, never a bare ValueError
            services.reissue_agreement(instance.pk, r.agreement_decider)
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "issued"  # the refusal rolled back
    services.reissue_agreement(instance.pk, r.agreement_decider)
    with pytest.raises(services.Refused, match="already_superseded"):
        services.reissue_agreement(instance.pk, r.agreement_decider)


def test_hdg6_a_deeply_nested_webhook_body_gets_the_uniform_answer(r, monkeypatch):
    issued(r, monkeypatch)
    before = completion.ProviderObservation.objects.count()
    response = post(b"[" * 30000 + b"]" * 30000)  # under the size cap, deeper than the parser's recursion limit
    assert (response.status_code, response.content) == (200, b"")
    assert completion.ProviderObservation.objects.count() == before


def test_hdg6_an_advance_that_keeps_failing_ends_with_a_staff_item(r, monkeypatch):
    app = issued(r, monkeypatch)
    monkeypatch.setattr(completion, "next_step", lambda application: (_ for _ in ()).throw(RuntimeError("defect")))
    completion.enqueue_advance(Application.objects.get(pk=app.pk))
    run_worker()
    assert PendingAction.objects.get(kind="advance_agreements").status == "failed"
    assert items(app, completion.ADVANCE_FAILED).count() == 1


def test_hdg6_a_false_completion_hint_is_reset_by_the_read(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    body = r.fake.webhook(instance.envelope_id)
    body["payload"]["status"] = "COMPLETED"  # claimed, not true at the provider
    post(body)
    assert nda(app).signing_status == "signing_complete_observed"
    reads_now()
    assert nda(app).signing_status == "not_started"


def test_hdg6_a_hint_never_moves_an_instance_that_was_not_issued(r, monkeypatch):
    app = admitted(r, monkeypatch)
    approve(r)
    activate()
    assert ledger.run_one()  # step 1 only: the instance exists, nothing sent
    instance = nda(Application.objects.get(pk=app.pk))
    hint = {"event": "DOCUMENT_COMPLETED", "payload": {"id": 1, "externalId": instance.external_key, "status": "COMPLETED",
                                                       "templateId": 101, "recipients": []}}
    assert post(hint).status_code == 200
    assert nda(app).signing_status == "not_started" and nda(app).issue_status == "create_pending"


def test_hdg6_a_lost_webhook_cannot_hide_a_late_completion_of_a_closed_instance(r, monkeypatch, settings):
    app = admitted(r, monkeypatch)
    approve(r)
    activate()
    monkeypatch.setattr(handlers.CreateAgreement, "after_call",  # stopped before the distribute: a draft is left
                        lambda self, claim, result: services.stop_agreements(app.pk, r.agreement_decider, "on_hold"))
    run_worker()
    instance = AgreementInstance.objects.get(application=app)
    assert instance.issue_status == "cancelled" and r.fake.envelopes[instance.envelope_id]["status"] == "DRAFT"
    run_worker()  # the draft is never distributed; bounded follow-up reads watch it
    # No webhook arrives; the provider later shows the draft completed (a provider-side act Catalyst never made).
    r.fake.envelopes[instance.envelope_id]["status"] = "COMPLETED"
    assert PendingAction.objects.filter(kind="read_agreement", idempotency_key__contains=":closed:").exists()  # armed
    reads_now()
    assert items(app, completion.COMPLETED_AFTER_CANCEL).count() == 1
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status == "cancelled"  # never verified


def test_hdg6_the_closed_follow_up_ends_visibly(r, monkeypatch, settings):
    app = issued(r, monkeypatch)
    instance = nda(app)
    AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="superseded")  # closed, provider still pending
    for _ in range(settings.CATALYST_AGREEMENT_ORPHAN_CHECKS + 2):
        completion.enqueue_read(AgreementInstance.objects.get(pk=instance.pk))
        reads_now()
        PendingAction.objects.filter(kind="read_agreement", status="queued").update(due_at=timezone.now())
    assert items(app, completion.CLOSED_WATCH_ENDED).count() == 1


def test_hdg6_a_follow_up_read_keeps_the_minimum_interval_after_a_running_read(r, monkeypatch, settings):
    app = issued(r, monkeypatch)
    instance = nda(app)
    real = provider.read

    def read(envelope_id):  # a hint arrives while this read is running
        post(r.fake.webhook(instance.envelope_id, "DOCUMENT_OPENED"))
        return real(envelope_id)
    monkeypatch.setattr(provider, "read", read)
    reads_now()
    follow_up = PendingAction.objects.get(kind="read_agreement", status="queued")
    last = completion.ProviderObservation.objects.filter(instance=instance, source="read").latest("id").observed_at
    assert (follow_up.due_at - last).total_seconds() >= settings.CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS - 1


# --- D-41: provider email ------------------------------------------------------------------------------------------

def test_d41_provider_email_is_inventoried_and_the_cancellation_email_suppressed(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    assert [m["kind"] for m in r.fake.emails] == ["signing_request"]  # provider-owned, not a Catalyst send
    env = r.fake.envelopes[instance.envelope_id]
    assert env["_email"]["documentDeleted"] is False and env["_email"]["recipientSigningRequest"] is True
    services.cancel_agreement(instance.pk, r.agreement_decider)
    run_worker()
    assert [m["kind"] for m in r.fake.emails] == ["signing_request"] and env["status"] == "CANCELLED"
    sent = [json.loads(c["body"]) for c in r.fake.calls("POST", "/envelope/cancel")]
    assert sent == [{"envelopeId": instance.envelope_id, "reason": provider.CANCEL_REASON}]  # never staff notes


def test_d41_the_suppression_is_sent_on_create_and_distribute(r, monkeypatch):
    issued(r, monkeypatch)
    use = r.fake.calls("POST", "/envelope/use")[0]["body"]
    distribute = json.loads(r.fake.calls("POST", "/envelope/distribute")[0]["body"])
    assert b'"documentDeleted": false' in use
    assert distribute["meta"]["emailSettings"] == provider.EMAIL_SETTINGS  # never left to the all-on default


# --- D-42: hold, resume and reissue ------------------------------------------------------------------------------------

def test_d42_a_hold_cancels_a_partly_signed_envelope_and_resume_issues_a_new_instance(r, monkeypatch):
    app = issued(r, monkeypatch)
    old = nda(app)
    r.fake.sign(old.envelope_id, complete=False)
    reads_now()
    assert nda(app).signing_status == "partially_signed"
    services.stop_agreements(app.pk, r.agreement_decider, "on_hold")
    with pytest.raises(services.Refused, match="cancellation_not_reconciled"):
        services.resume_agreements(app.pk, r.agreement_decider)  # not before the cancel has settled
    run_worker()
    old.refresh_from_db()
    assert old.issue_status == "cancelled" and r.fake.envelopes[old.envelope_id]["status"] == "CANCELLED"
    services.resume_agreements(app.pk, r.agreement_decider)
    run_worker()
    new = instances(app).last()
    assert new.pk != old.pk and new.external_key != old.external_key and new.issue_status == "issued"
    assert new.signing_status == "not_started"  # no partial signature is carried over
    assert AgreementInstance.objects.get(pk=old.pk).signing_status == "cancelled"  # history unchanged


def test_d42_a_cancelled_agreement_is_never_reissued_without_a_decision_maker(r, monkeypatch):
    app = issued(r, monkeypatch)
    services.cancel_agreement(nda(app).pk, r.agreement_decider)
    run_worker()
    completion.enqueue_advance(Application.objects.get(pk=app.pk))  # an automatic trigger
    run_worker()
    assert instances(app).count() == 1 and items(app, completion.REISSUE_NEEDS_DECISION).count() == 1


def test_d42_withdrawal_is_not_resumable_and_a_verified_agreement_is_never_cancelled(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    r.fake.sign(instance.envelope_id)
    reads_now()
    assert services.stop_agreements(app.pk, r.agreement_decider, "withdrawn") == []  # verified: kept as signed
    assert nda(app).signing_status == "signing_complete_verified"
    with pytest.raises(services.Refused, match="stopped_for_good"):
        services.resume_agreements(app.pk, r.agreement_decider)


# --- D-43: agreement integrity ------------------------------------------------------------------------------------------

def held_nda(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    r.fake.sign(instance.envelope_id)
    reads_now()  # verified; the custody gate (4B.3) keeps the User Agreement back for now
    stranger = {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"}
    r.fake.envelopes[instance.envelope_id]["recipients"].append(stranger)  # changed at the provider after verification
    completion.enqueue_read(nda(app))
    reads_now()
    assert items(app, completion.INTEGRITY_HOLD).count() == 1
    signing_gate(r)  # from here the NDA's own gate would pass; only the integrity hold holds it
    return app, nda(app)


def test_d43_a_changed_recipient_after_verification_holds_reliance_until_a_reasoned_resolution(r, monkeypatch):
    app, instance = held_nda(r, monkeypatch)
    try:
        assert instance.signing_status == "signing_complete_verified"  # the historical fact is kept
        assert not completion.gate_passed(instance)
        completion.enqueue_advance(Application.objects.get(pk=app.pk))
        run_worker()
        assert not instances(app, "user_agreement").exists()  # no User Agreement on a held NDA
        with pytest.raises(services.Refused, match="integrity_hold_open"):
            services.resume_agreements(app.pk, r.agreement_decider)  # generic resume never clears it
        state = services.integrity_state(instance)
        for user in (r.decider, staff(r, "root-integrity", superuser=True)):
            with pytest.raises(PermissionDenied):
                services.resolve_integrity(instance.pk, user, "continue", "Provider shows a stranger.", state["digest"])
        with pytest.raises(services.Refused, match="reason_needed"):
            services.resolve_integrity(instance.pk, r.agreement_decider, "continue", "short", state["digest"])
        with pytest.raises(services.Refused, match="no_fresh_matching_read"):
            services.resolve_integrity(instance.pk, r.agreement_decider, "continue", "Checked the provider view.",
                                       state["digest"])
        services.resolve_integrity(instance.pk, r.agreement_decider, "escalate", "Needs counsel on the extra signer.",
                                   state["digest"])
        assert items(app, completion.INTEGRITY_HOLD).count() == 1  # escalation keeps it blocked
        # The provider's view is corrected; a fresh read then supports continuing.
        r.fake.envelopes[instance.envelope_id]["recipients"].pop()
        services.recheck_integrity(instance.pk, r.agreement_decider)
        reads_now()
        with pytest.raises(services.Refused, match="changed_since_shown"):  # the state shown is stale after the read
            services.resolve_integrity(instance.pk, r.agreement_decider, "continue", "Provider view corrected.",
                                       state["digest"])
        fresh = services.integrity_state(instance)
        assert fresh["matching"]
        services.resolve_integrity(instance.pk, r.agreement_decider, "continue", "Provider view corrected.",
                                   fresh["digest"])
        assert not items(app, completion.INTEGRITY_HOLD).exists() and completion.gate_passed(nda(app))
        run_worker()  # the sequence continues where the hold stopped it
        assert instances(app, "user_agreement").count() == 1
    finally:
        reset_gate(r)


def test_d43_replacement_makes_a_new_generation_eligible_and_keeps_the_verified_history(r, monkeypatch):
    app, instance = held_nda(r, monkeypatch)
    try:
        state = services.integrity_state(instance)
        new = services.resolve_integrity(instance.pk, r.agreement_decider, "replace",
                                         "Replace with a fresh NDA for the applicant only.", state["digest"])
        old = AgreementInstance.objects.get(pk=instance.pk)
        assert old.replaced_at and old.signing_status == "signing_complete_verified"  # history kept, not eligible
        assert old.recipients.count() == 1  # the expected recipients never change to match the provider
        assert new.pk != old.pk and new.external_key != old.external_key
        run_worker()
        assert AgreementInstance.objects.get(pk=new.pk).issue_status == "issued"
        assert completion.next_step(Application.objects.get(pk=app.pk))[2] == "waiting_for_gate"  # the new one must pass
    finally:
        reset_gate(r)


# --- D-44: the orphan watch and the new database protections -----------------------------------------------------------

def test_d44_the_orphan_watch_ends_visibly_and_is_re_armed_a_bounded_number_of_times(r, monkeypatch):
    app = admitted(r, monkeypatch)
    approve(r)
    activate()
    r.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    services.decide_uncertain_create(instance.pk, r.agreement_decider, "abandon")
    run_worker()
    attempt = EnvelopeAttempt.objects.get(external_key=instance.external_key, step="create")
    assert items(app, handlers.ORPHAN_WATCH_ENDED).count() == 1  # never a silent end
    for _ in range(handlers.MAX_WATCH_REARMS):
        services.rearm_orphan_watch(attempt.pk, r.agreement_decider)
        assert not items(app, handlers.ORPHAN_WATCH_ENDED).exists()
        run_worker()
        assert items(app, handlers.ORPHAN_WATCH_ENDED).count() == 1
    with pytest.raises(services.Refused, match="rearm_limit_reached"):
        services.rearm_orphan_watch(attempt.pk, r.agreement_decider)


def test_d42_d43_the_new_columns_are_set_once_for_every_role(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    roles = {role: r.committed.connect(role, autocommit=True) for role in ("app", "owner")}
    with pytest.raises(errors.CheckViolation):  # one known reason code, set together with the timestamp
        roles["owner"].execute("UPDATE agreements_agreementinstance SET replaced_at = now(), replacement_reason = 'other'"
                               " WHERE id = %s", [instance.pk])
    roles["app"].execute("UPDATE agreements_agreementinstance SET cancel_requested_at = now() WHERE id = %s", [instance.pk])
    with pytest.raises(errors.InsufficientPrivilege, match="needs its reason"):
        roles["app"].execute("UPDATE agreements_agreementinstance SET replaced_at = now() WHERE id = %s", [instance.pk])
    roles["app"].execute("UPDATE agreements_agreementinstance SET replaced_at = now(), replacement_reason = 'integrity_replaced' WHERE id = %s",
                         [instance.pk])
    for conn in roles.values():
        for sql in ("UPDATE agreements_agreementinstance SET cancel_requested_at = now() + interval '1 day' WHERE id = %s",
                    "UPDATE agreements_agreementinstance SET replacement_reason = 'y' WHERE id = %s"):
            with pytest.raises(errors.InsufficientPrivilege, match="recorded once"):
                conn.execute(sql, [instance.pk])


def test_d43_the_d15_backstop_ignores_a_replaced_nda(r, monkeypatch):
    app = issued(r, monkeypatch)
    instance = nda(app)
    ua = r.ua
    with r.committed.connect("app") as conn:
        conn.execute("INSERT INTO agreements_providerobservation (instance_id, application_id, source, event, envelope_status,"
                     " recipients, identity_match, recipients_match, all_required_signed, content_sha256, observed_at,"
                     " created_txid) VALUES (%s, %s, 'read', '', 'COMPLETED', '[]', true, true, true, 'z', now(), 0)",
                     [instance.pk, app.pk])
        conn.execute("UPDATE agreements_agreementinstance SET signing_status = 'signing_complete_verified' WHERE id = %s",
                     [instance.pk])
        conn.commit()
    app_conn = r.committed.connect("app", autocommit=True)
    app_conn.execute("UPDATE agreements_agreementinstance SET replaced_at = now(), replacement_reason = 'integrity_replaced' WHERE id = %s",
                     [instance.pk])
    with pytest.raises(errors.InsufficientPrivilege, match="D-15"):
        app_conn.execute("INSERT INTO agreements_agreementinstance (public_id, application_id, agreement_type_id,"
                         " template_version_id, external_key, envelope_id, issue_status, signing_status, custody_status,"
                         " created_at, updated_at) SELECT gen_random_uuid(), %s, t.id, %s, 'ag_ua_x', '', 'create_pending',"
                         " 'not_started', 'not_due', now(), now() FROM agreements_agreementtype t WHERE t.key = 'user_agreement'",
                         [app.pk, ua.pk])


# --- PR #42 review regressions ---------------------------------------------------------------------------------------

def test_review_replace_never_issues_after_a_stop_and_a_stopped_application_creates_nothing(r, monkeypatch):
    app, instance = held_nda(r, monkeypatch)
    try:
        assert services.stop_agreements(app.pk, r.agreement_decider, "withdrawn") == []  # the verified NDA stays
        state = services.integrity_state(instance)
        with pytest.raises(services.Refused, match="agreements_not_open"):
            services.resolve_integrity(instance.pk, r.agreement_decider, "replace",
                                       "Replace with a fresh NDA for the applicant.", state["digest"])
        assert instances(app).count() == 1 and len(r.fake.calls("POST", "/envelope/use")) == 1
    finally:
        reset_gate(r)


def test_review_a_withdrawal_cannot_be_downgraded_to_a_resumable_hold(r, monkeypatch):
    app = issued(r, monkeypatch)
    services.stop_agreements(app.pk, r.agreement_decider, "withdrawn")
    with pytest.raises(services.Refused, match="stopped_for_good"):
        services.stop_agreements(app.pk, r.agreement_decider, "on_hold")
    with pytest.raises(services.Refused, match="stopped_for_good"):
        services.resume_agreements(app.pk, r.agreement_decider)


def test_review_resume_never_reissues_over_a_completion_after_cancel(r, monkeypatch):
    app = issued(r, monkeypatch)
    old = nda(app)
    services.stop_agreements(app.pk, r.agreement_decider, "on_hold")
    run_worker()
    r.fake.envelopes[old.envelope_id]["status"] = "COMPLETED"  # the provider later shows the cancelled one completed
    post(r.fake.webhook(old.envelope_id))
    reads_now()
    assert items(app, completion.COMPLETED_AFTER_CANCEL).count() == 1
    services.resume_agreements(app.pk, r.agreement_decider)
    run_worker()
    assert instances(app).count() == 1 and items(app, completion.REISSUE_NEEDS_DECISION).count() == 1


def test_review_a_user_agreement_is_not_reissued_while_the_nda_is_held(r, monkeypatch):
    app = issued(r, monkeypatch)
    signing_gate(r)
    try:
        instance = nda(app)
        r.fake.sign(instance.envelope_id)
        reads_now()
        ua = instances(app, "user_agreement").get()
        r.fake.reject(ua.envelope_id)
        reads_now()
        assert AgreementInstance.objects.get(pk=ua.pk).signing_status == "declined"
        r.fake.envelopes[instance.envelope_id]["recipients"].append(
            {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
        completion.enqueue_read(nda(app))
        reads_now()
        assert items(app, completion.INTEGRITY_HOLD).count() == 1
        with pytest.raises(services.Refused, match="earlier_agreement_not_passed"):
            services.reissue_agreement(ua.pk, r.agreement_decider)
    finally:
        reset_gate(r)


def test_review_protective_cancel_runs_while_paused_and_while_a_hard_bounce_is_open(r, monkeypatch):
    from workflow.models import AutomationPause

    app = issued(r, monkeypatch)
    instance = nda(app)
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    StaffItem.objects.create(application=Application.objects.get(pk=app.pk), reason_code="hard_bounce",
                             dedupe_key="inbound:synthetic")
    services.cancel_agreement(instance.pk, r.agreement_decider)
    run_worker()
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "cancelled"
    assert r.fake.envelopes[instance.envelope_id]["status"] == "CANCELLED"
    assert [m["kind"] for m in r.fake.emails] == ["signing_request"]  # no cancellation email, nothing new sent


def test_review_a_requested_cancel_closes_a_pending_create_without_calling_the_provider(r, monkeypatch):
    app = admitted(r, monkeypatch)
    approve(r)
    activate()
    assert ledger.run_one()  # step 1: the instance, its create queued
    instance = nda(Application.objects.get(pk=app.pk))
    r.committed.connect("app", autocommit=True).execute(
        "UPDATE agreements_agreementinstance SET cancel_requested_at = now() WHERE id = %s", [instance.pk])
    run_worker()
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "cancelled"
    assert not r.fake.calls("POST", "/envelope/use") and app.events.filter(kind="agreement_closed_on_request").exists()


def test_review_an_unknown_create_found_after_a_stop_is_kept_undistributed_and_watched(r, monkeypatch):
    app = admitted(r, monkeypatch)
    approve(r)
    activate()
    r.fake.fault("POST /envelope/use", ("drop_after",))  # created at the provider, the answer lost
    monkeypatch.setattr(handlers.CreateAgreement, "after_call",
                        lambda self, claim, result: services.stop_agreements(app.pk, r.agreement_decider, "on_hold"))
    run_worker()
    instance = AgreementInstance.objects.get(application=app)
    assert instance.issue_status == "cancelled" and instance.envelope_id  # found by evidence, recorded, closed
    assert not r.fake.calls("POST", "/envelope/distribute")
    assert r.fake.envelopes[instance.envelope_id]["status"] == "DRAFT"
    assert PendingAction.objects.filter(kind="read_agreement", idempotency_key__contains=":closed:").exists()

