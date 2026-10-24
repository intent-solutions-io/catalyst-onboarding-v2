"""First-slice acceptance (S1-T8; 005 S1.7, GATE-S1): the whole-flow cases TEST-S1-15 and TEST-S1-16, the
parts of TEST-S1-14 and TEST-S1-20 no earlier task covered, and the checks that keep the acceptance map
(tests/acceptance.py) honest.

The flow is always the real one: an intake POST, the real worker command sending to the local sink, the
link read from the sink, the confirmation GET and POST, a later repeat, and staff reading the dossier.
These tests commit (`privileged_reset`), like the worker and staff tests they compose.
"""

import importlib
import json
import logging
import re
import subprocess
import sys
import uuid
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode

import pytest
from django.apps import apps
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.urls import reverse

from applications.models import Application, ContactChallenge
from config import runtime
from correspondence import verification
from tests import acceptance, support
from tests.conftest import case_status
from tests.test_intake import failing_on
from tests.test_staff import PASSWORD, change_url, logged_in, make_user
from tests.test_worker import Crash, expire_lease
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

ROOT = Path(__file__).resolve().parent.parent
FORM = reverse("applications:request_access")
VALID = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}
REPEAT_REASON = "A synthetic repeat after verification."


def submit(client=None, **fields):
    return (client or Client()).post(FORM, urlencode({**VALID, **fields}), content_type="application/x-www-form-urlencoded")


def run_worker():
    call_command("run_worker", exit_when_idle=True, stdout=StringIO())


def link_from_sink():
    assert mail.outbox, "the worker sent nothing"
    match = re.search(re.escape(settings.CATALYST_PUBLIC_BASE_URL) + r"(/confirm/(\S+)/)", mail.outbox[-1].body)
    assert match, mail.outbox[-1].subject
    return match.group(1), match.group(2)  # path, token


def confirm(path, version=None):
    """Open the link and confirm the version it shows, or post `version` again (a used link has no form)."""
    if version is None:
        page = Client().get(path)
        version = re.search(r'name="version" value="([^"]+)"', page.content.decode()).group(1)
    return Client().post(path, {"version": version}), version


@pytest.fixture
def flow(privileged_reset, monkeypatch, settings):
    """In-process worker runs declare a worker process, as the real command does."""
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    return privileged_reset


# --- TEST-S1-15: history completeness ---------------------------------------------------------------------------

def test_s1_15_the_whole_flow_writes_exactly_the_expected_history(flow):
    assert submit().status_code == 302
    run_worker()
    path, _ = link_from_sink()
    response, version = confirm(path)
    assert response.status_code == 200
    again = confirm(path, version)[0]
    assert again.status_code == 200 and "already confirmed" in again.content.decode()  # no new history
    assert submit(reason=REPEAT_REASON).status_code == 302  # a repeat after verification
    run_worker()  # nothing claimable: the held action is never run

    app = Application.objects.get()
    send = PendingAction.objects.get(kind="send_verification")
    history = list(app.events.order_by("occurred_at", "id").values_list("kind", "actor_type", "actor_ref", "data"))
    assert history == [
        ("submission_received", "applicant", "", {"version_number": 1}),
        ("verification_sent", "system", f"pending_action:{send.pk}", {"attempt": 1, "template_version": "s1-synthetic-1"}),
        ("contact_verified", "applicant", "", {"version_number": 1}),
        ("repeat_submission", "applicant", "", {"version_number": 2}),
        ("needs_staff_attention", "applicant", "", {"version_number": 2, "reason": "repeat_after_verification"}),
    ]
    assert list(app.versions.order_by("version_number").values_list("version_number", "origin")) == [
        (1, "form"), (2, "repeat_after_verification")]
    assert app.adoptions.get().submission_version.version_number == 1
    assert sorted(PendingAction.objects.values_list("kind", "status", "attempts")) == [
        ("send_verification", "done", 1), ("start_evidence_collection", "held", 0)]
    assert app.outbound_messages.count() == 1 and len(mail.outbox) == 1
    assert ContactChallenge.objects.count() == 1


@pytest.mark.parametrize("superuser", [False, True], ids=["read-only-staff", "django-superuser"])
def test_s1_15_no_one_can_change_or_delete_versions_or_events_through_the_admin(flow, superuser):
    """Versions and events appear only as read-only rows inside the dossier; there is no page that edits
    them, and a forged inline formset on the dossier is refused (the database refuses them as well,
    TEST-S1-21)."""
    assert submit().status_code == 302
    app = Application.objects.get()
    client = logged_in(make_user(flow, "editor", group=not superuser, superuser=superuser))
    for model in ("submissionversion", "applicationevent", "contactchallenge", "versionadoption"):
        assert client.get(f"/staff/applications/{model}/").status_code == 404
        assert client.get(f"/staff/applications/{model}/1/change/").status_code == 404
        assert client.post(f"/staff/applications/{model}/1/delete/", {"post": "yes"}).status_code == 404
    version, event = app.versions.get(), app.events.get()
    forged = {
        "versions-TOTAL_FORMS": "1", "versions-INITIAL_FORMS": "1", "versions-0-id": version.pk,
        "versions-0-submitted_fields": '{"name": "Changed"}', "versions-0-DELETE": "on",
        "events-TOTAL_FORMS": "1", "events-INITIAL_FORMS": "1", "events-0-id": event.pk,
        "events-0-DELETE": "on", "_save": "Save",
    }
    assert client.post(change_url(app), forged).status_code == 403
    page = client.get(change_url(app)).content.decode()
    assert 'name="versions-0-DELETE"' not in page and 'name="_save"' not in page
    version.refresh_from_db()
    event.refresh_from_db()
    assert version.submitted_fields == VALID and event.kind == "submission_received"


# --- TEST-S1-16: no token, address or name in any log record across the whole flow ---------------------------------

class Capture(logging.Handler):
    """Attached to the root logger and to the loggers that do not propagate to it, so nothing escapes."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.format(record)  # fills exc_text, so a traceback's text is checked too
        self.records.append(record)


def test_s1_16_no_log_record_across_the_whole_flow_carries_a_token_address_or_name(flow, caplog, monkeypatch, settings):
    settings.CATALYST_WORKER_RETRY_SECONDS = 0  # the failed first send is retried at once
    sends = []
    real_send = verification.EmailMessage.send

    def fail_once(message, *args, **kwargs):
        sends.append(1)
        if len(sends) == 1:
            raise ConnectionRefusedError("synthetic sink outage")
        return real_send(message, *args, **kwargs)
    monkeypatch.setattr(verification.EmailMessage, "send", fail_once)
    capture = Capture()
    names = [""] + [name for name, logger in logging.root.manager.loggerDict.items()
                    if isinstance(logger, logging.Logger) and not logger.propagate]
    previous = {}
    for name in names:
        logger = logging.getLogger(name)
        previous[name] = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(capture)
    try:
        public = Client(enforce_csrf_checks=True)
        assert submit(name="", email="not-an-address").status_code == 200  # form errors
        assert submit(public).status_code == 403  # no CSRF token
        assert Client().post(FORM, "x" * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1024), content_type="application/x-www-form-urlencoded").status_code == 400
        with connection.execute_wrapper(failing_on("workflow_pendingaction")):
            assert submit().status_code == 503  # a database failure: nothing committed
        assert submit().status_code == 302
        run_worker()  # attempt 1 fails at the sink, attempt 2 sends
        assert len(sends) == 2 and PendingAction.objects.get().status == "done"
        path, token = link_from_sink()
        assert Client().get(path[:-12] + "AAAAAAAAAAA/").status_code == 404  # tampered
        assert Client().put(path).status_code == 405
        assert Client(enforce_csrf_checks=True).post(path, {"version": "x"}).status_code == 403
        assert Client().post(path, {"version": "not-a-version"}).status_code == 400
        response, version = confirm(path)
        assert response.status_code == 200
        assert confirm(path, version)[0].status_code == 200  # already confirmed
        assert submit(reason=REPEAT_REASON).status_code == 302
        app = Application.objects.get()
        make_user(flow, "reader")
        staff = Client()
        assert staff.post(reverse("admin:login"), {"username": "reader", "password": "wrong"}).status_code == 200
        assert staff.post(reverse("admin:login"), {"username": "reader", "password": PASSWORD}).status_code == 302
        assert staff.get(change_url(app)).status_code == 200
        assert staff.post(change_url(app), {"stage": "admitted"}).status_code == 403
        assert staff.get(f"{reverse('admin:workflow_pendingaction_changelist')}?input_ref__startswith=0").status_code == 400
        assert staff.post(reverse("admin:logout")).status_code == 200
    finally:
        for name in names:
            logging.getLogger(name).removeHandler(capture)
            logging.getLogger(name).setLevel(previous[name])

    records = capture.records
    assert len(records) >= 12  # the flow did log: refusals, 4xx lines, the failed send, the 503
    challenge = ContactChallenge.objects.get()
    secrets = [token, path, str(challenge.public_id), VALID["email"], VALID["name"], VALID["reason"], REPEAT_REASON,
               PASSWORD, settings.CATALYST_VERIFICATION_KEY, settings.SECRET_KEY]
    for record in records:
        text = " ".join([record.getMessage(), str(record.exc_text or ""), repr(getattr(record, "request", ""))])
        for secret in secrets:
            assert secret not in text, (record.name, record.levelname)
    logged = {r.name for r in records}
    assert {"applications.views", "correspondence.verification", "django.request", "django.security.csrf"} <= logged, logged
    assert any("intake submission did not complete" in r.getMessage() for r in records)
    assert any("send failed (ConnectionRefusedError)" in r.getMessage() for r in records)
    assert not any("synthetic sink outage" in " ".join([r.getMessage(), str(r.exc_text or "")]) for r in records)
    assert any(r.getMessage() == "Not Found: /confirm/[redacted]/" for r in records)


# --- TEST-S1-14 (remaining part): CI has no provider secrets ---------------------------------------------------------

def test_s1_14_ci_receives_no_provider_secret():
    """The runtime lane's workflow references no repository secret at all, and every variable it sets is a
    synthetic value; none uses a provider prefix or name the start-up guard refuses."""
    from config.guards import PROVIDER_ENV_NAMES, PROVIDER_ENV_PREFIXES

    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "secrets." not in ci
    names = re.findall(r"^\s+([A-Z][A-Z0-9_]+):", ci, flags=re.M)
    assert names and not [n for n in names if n.startswith(PROVIDER_ENV_PREFIXES) or n in PROVIDER_ENV_NAMES]
    for value in re.findall(r"_(?:PASSWORD|KEY): *\"?([^\"\s#]+)", ci):
        assert value.startswith("synthetic-"), value


# --- TEST-S1-20 (remaining parts): constraints by introspection; no orphans ------------------------------------------

DATABASE_CONSTRAINTS = {
    "application_one_open_per_email_key", "application_stage_valid", "application_next_version_positive",
    "version_number_unique_per_application", "version_number_positive", "version_origin_valid",
    "version_id_application_unique", "challenge_one_active_per_application", "challenge_expires_after_creation",
    "challenge_id_application_unique", "adoption_one_per_application", "adoption_version_same_application",
    "adoption_challenge_same_application", "event_actor_type_valid", "pending_action_status_valid",
    "pending_action_max_attempts_positive", "pending_action_attempts_bounded", "pending_action_running_has_lease",
    "pause_one_per_subject", "outbound_unique_per_attempt", "outbound_attempt_positive", "outbound_status_valid",
    # P2 2B.1 outbound foundations (016 section 3; correspondence migration 0003)
    "outbound_attempt_number_per_message", "template_version_unique", "template_version_positive",
    "template_version_status_valid", "template_version_approved_has_approver", "template_version_link_is_secret_bearing",
    "question_status_valid", "question_approval_valid", "question_origin_valid", "question_approved_has_approver",
    "approved_message_kind_valid", "approved_message_authority_valid", "approved_message_disposition_valid",
    "approved_message_template_required", "approved_message_has_content", "approved_message_authorized",
    "approved_message_not_self_superseding", "message_question_unique", "question_one_initial_message",
    "message_question_purpose_valid", "staff_item_one_open_per_key", "staff_item_status_valid",
    "staff_item_resolution_has_actor",
    # P2 2B.2 inbound collection (016 sections 3.3, 3.5, 3.6; correspondence migration 0005)
    "cursor_one_per_folder", "cursor_state_valid", "cursor_last_uid_nonnegative", "inbound_status_valid",
    "inbound_is_derivative", "inbound_identity_state_valid", "inbound_one_per_digest", "inbound_location_unique",
    "inbound_location_matched_by_valid", "reply_link_unique", "reply_link_state_valid", "reply_link_outcome_valid",
    "approved_message_staff_draft_iff_staff_message", "staff_draft_complete",
    "evidence_source_version_unique", "evidence_source_one_approved_version", "evidence_source_version_positive",
    "evidence_source_kind_valid", "evidence_source_status_valid", "evidence_source_on_unavailable_valid",
    "evidence_source_port_valid", "evidence_source_approved_has_approver", "evidence_item_one_per_claim_round",
    "evidence_item_status_valid", "evidence_item_round_positive", "evidence_item_terminal_has_time",
    "evidence_item_id_application_unique", "evidence_capture_one_per_attempt", "evidence_capture_is_derivative",
    "evidence_capture_outcome_valid", "evidence_capture_id_application_unique",
    "evidence_item_version_same_application", "evidence_capture_item_same_application",
    "assessment_run_status_valid", "assessment_run_round_positive", "assessment_run_one_success_per_snapshot",
    "assessment_run_one_in_flight", "assessment_run_success_has_output", "assessment_run_terminal_has_time",
    "assessment_invocation_one_per_attempt", "assessment_invocation_status_valid",
    "question_text_unique_while_live", "reply_interpretation_one_per_attempt", "reply_interpretation_status_valid",
    "reply_interpretation_finished_has_time",
    "decision_outcome_valid", "decision_basis_valid", "decision_basis_matches_run", "decision_one_final_per_application", "decision_human_only_has_code",
    # P4 4B.1 (021 section 3)
    "agreement_template_one_per_version", "agreement_template_status_valid", "agreement_template_approved_has_actor",
    "agreement_issue_status_valid", "agreement_signing_status_valid", "agreement_custody_status_valid",
    "agreement_one_live_per_type", "agreement_external_key_unique", "agreement_envelope_unique",
    "agreement_recipient_one_per_slot", "agreement_recipient_who_valid", "envelope_attempt_step_valid",
    "envelope_attempt_outcome_valid", "observation_source_valid", "observation_webhook_once",  # 4B.2
    "agreement_replacement_consistent",  # D-43
    # P5 5B.1 (023 section 4)
    "reservation_live_address_unique",
    "reservation_basis_valid",
    "reservation_exception_reviewed",
    "reservation_local_part_safe",
    "provisioning_one_live_request",
    "provisioning_status_valid",
    "provisioning_method_valid",
    "provisioning_quota_positive",
    "provisioning_send_limit_range",
    "provisioning_approval_consistent",
    "provisioning_progress_needs_approval",
    "provisioning_not_self_superseding",
    "provisioning_evidence_kind_valid",
    "provisioning_evidence_has_actor",
    "provisioning_attempt_step_valid",
    "provisioning_attempt_outcome_valid",
    "provisioning_one_open_create",
    "setup_series_unique", "setup_one_live_per_request", "setup_token_unique", "setup_state_valid",  # 5B.2
    "setup_invited_has_token", "setup_completed_consistent",
    "revocation_one_per_kind", "revocation_kind_valid", "revocation_state_valid", "revocation_exception_decided",  # 5B.3
    "withdrawal_token_unique", "withdrawal_one_live_per_application", "withdrawal_state_valid", "withdrawal_has_requester",
    "invitation_one_live_per_email_key", "invitation_expires_after_issue", "invitation_has_issuer",  # 9kg.43
    "member_on_file_one_live_per_email_key", "member_on_file_completion_verified",  # 9kg.52
    "member_on_file_covers_something", "member_on_file_has_recorder",
    "stored_document_one_per_item", "stored_document_signed_only", "document_access_outcome_valid",  # 4B.3
    "details_one_per_version", "details_status_valid", "details_confirmed_has_actor",
}


@pytest.mark.django_db
def test_s1_20_every_named_constraint_exists_in_the_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
                       " WHERE n.nspname = current_schema()")
        names = {r[0] for r in cursor.fetchall()}
        cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
        names |= {r[0] for r in cursor.fetchall()}  # partial unique constraints are unique indexes
    assert DATABASE_CONSTRAINTS <= names, DATABASE_CONSTRAINTS - names
    # The list above covers every constraint the models declare (plus the two composite foreign keys).
    declared = {c.name for label in ("applications", "workflow", "correspondence", "assessments", "agreements",
                                     "provisioning")
                for model in apps.get_app_config(label).get_models() for c in model._meta.constraints}
    assert declared <= DATABASE_CONSTRAINTS, declared - DATABASE_CONSTRAINTS


def orphans():
    """Workflow rows carry no foreign key (ADR-01), so references are checked by query: every action and
    pause names an existing application; every send's input is that application's challenge and the
    next-stage action's input is its adopted version; every outbound message matches its action."""
    found = []
    for action in PendingAction.objects.all():
        app = Application.objects.filter(public_ref=action.subject_id).first()
        if action.subject_type != "application" or app is None:
            found.append(f"action {action.pk}: missing subject")
        elif action.kind == "send_verification" and not ContactChallenge.objects.filter(
                application=app, public_id=action.input_ref).exists():
            found.append(f"action {action.pk}: missing challenge")
        elif action.kind == "start_evidence_collection" and not app.adoptions.filter(
                submission_version__public_id=action.input_ref).exists():
            found.append(f"action {action.pk}: input is not the adopted version")
    for pause in AutomationPause.objects.all():
        if pause.subject_type != "application" or not Application.objects.filter(public_ref=pause.subject_id).exists():
            found.append(f"pause {pause.pk}: missing subject")
    for message in apps.get_model("correspondence", "OutboundMessage").objects.all():
        if str(message.pending_action.subject_id) != str(message.application.public_ref):
            found.append(f"message {message.pk}: action and application disagree")
    return found


def test_s1_20_no_workflow_row_points_at_a_missing_subject_or_input(flow):
    submit()
    PendingAction.objects.update(status="failed")
    submit(reason="A second synthetic reason.")  # supersedes: a second challenge and send
    run_worker()
    confirm(link_from_sink()[0])
    app = Application.objects.get()
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="staff:test")
    assert PendingAction.objects.count() == 3 and AutomationPause.objects.count() == 1
    assert orphans() == []
    # Negative control: the check does detect a dangling reference.
    ghost = uuid.uuid4()
    PendingAction.objects.create(kind="send_verification", subject_type="application", subject_id=ghost,
                                 input_ref=str(uuid.uuid4()), idempotency_key=f"probe:{ghost}")
    AutomationPause.objects.create(subject_type="application", subject_id=ghost, reason="synthetic", actor_ref="staff:test")
    assert [o.split(":")[1].strip() for o in orphans()] == ["missing subject", "missing subject"]


# --- TEST-S1-11 (remaining part): an established non-staff session ---------------------------------------------------

def test_s1_11_an_established_non_staff_session_reaches_no_staff_page(flow):
    assert submit().status_code == 302
    app = Application.objects.get()
    client = logged_in(make_user(flow, "outsider", staff=False))
    for url in (reverse("admin:index"), reverse("admin:applications_application_changelist"), change_url(app),
                reverse("admin:workflow_pendingaction_changelist")):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"].startswith(reverse("admin:login"))
        assert all(value not in response.content.decode() for value in VALID.values())
        assert all(value not in client.get(response["Location"]).content.decode() for value in VALID.values())


# --- TEST-S1-18 (remaining part): a handler that crashes the worker on every attempt -------------------------------

def test_s1_18_a_handler_that_crashes_the_worker_on_every_attempt_is_stopped_by_the_poison_rule(flow, monkeypatch):
    """The handler itself kills the process each time (a BaseException nothing catches). Attempts are counted
    at claim, so after the maximum the poison rule finishes the action without running the handler again."""
    assert submit().status_code == 302
    calls = []

    def crash(self, claim):
        calls.append(claim.attempt)
        raise Crash
    monkeypatch.setattr(verification.SendVerification, "run", crash)
    for attempt in (1, 2, 3):
        with pytest.raises(Crash):
            ledger.run_one()
        action = PendingAction.objects.get()
        assert (action.status, action.attempts) == ("running", attempt)
        expire_lease(action.pk)  # the dead worker's lease runs out
    run_worker()
    assert calls == [1, 2, 3]  # never a fourth time
    action = PendingAction.objects.get()
    assert (action.status, action.attempts, action.last_error) == ("failed", 3, "attempts exhausted")
    assert Application.objects.get().events.get(kind="action_attempts_exhausted").data == {"attempts": 3}
    assert mail.outbox == []


# --- the acceptance map itself --------------------------------------------------------------------------------------

GATE_PROBE_CONFTEST = """
from tests import acceptance
acceptance.CASES = {"TEST-PROBE": [%s]}
acceptance.SUPPORTING = {}
acceptance.P2_CASES = {}
acceptance.P3_CASES = {}
acceptance.P3_SUPPORTING = {}
acceptance.P4_CASES = {}
acceptance.P4_SUPPORTING = {}
acceptance.P5_CASES = {}
acceptance.P5_SUPPORTING = {}
acceptance.P6_CASES = {}
acceptance.P6_SUPPORTING = {}
acceptance.P6_LIVE_ONLY = {}
acceptance.P6_EVIDENCE = {}
"""


def gate_probe(tmp_path, mapped, *args):
    """A child pytest run of the real conftest in a throwaway project whose map is replaced: the same
    hooks decide, so a pytest upgrade that changes what counts as a full run is caught here."""
    (tmp_path / "conftest.py").write_text(GATE_PROBE_CONFTEST % ", ".join(repr(m) for m in mapped))
    (tmp_path / "test_probe.py").write_text("def test_ran():\n    assert True\n\ndef test_other():\n    assert True\n")
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=tmp_path, env=support.child_env(PYTHONPATH=str(ROOT)), capture_output=True, text=True,
                          timeout=120)


def test_the_gate_fails_a_full_run_with_a_case_not_pass_and_spares_a_selected_subset(tmp_path):
    complete = gate_probe(tmp_path, ["test_probe::test_ran", "test_probe::test_other"])
    assert complete.returncode == 0, complete.stdout
    assert "TEST-PROBE" in complete.stdout
    assert "numbered cases: PASS 1, FAIL 0, INCOMPLETE 0, NOT RUN 0 (full run" in complete.stdout
    missing = gate_probe(tmp_path, ["test_probe::test_ran", "test_probe::test_never_written"])
    assert missing.returncode == 1, missing.stdout  # every test passed: the gate alone fails the run
    assert "2 passed" in missing.stdout and "INCOMPLETE 1" in missing.stdout and "(full run" in missing.stdout
    subset = gate_probe(tmp_path, ["test_probe::test_ran", "test_probe::test_never_written"], "-k", "ran")
    assert subset.returncode == 0 and "selected subset: not gated" in subset.stdout, subset.stdout
    path_arg = gate_probe(tmp_path, ["test_probe::test_ran", "test_probe::test_never_written"], "test_probe.py")
    assert path_arg.returncode == 0 and "selected subset: not gated" in path_arg.stdout, path_arg.stdout
    for selection in (["-m", "not slow"], ["--deselect", "test_probe.py::test_other"]):
        selected = gate_probe(tmp_path, ["test_probe::test_ran", "test_probe::test_never_written"], *selection)
        assert selected.returncode == 0 and "selected subset: not gated" in selected.stdout, (selection, selected.stdout)


def test_ci_runs_the_whole_suite_with_no_selection():
    """The gate only binds a full run, so CI's runtime step must not select: no path, -k, -m or deselect."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    commands = re.findall(r"run: (.*-m pytest.*)$", ci, flags=re.M)
    assert commands == ["/tmp/venv/bin/python -m pytest -v"]
    assert "PYTEST_ADDOPTS" not in ci  # options injected through the environment could select too
    import tomllib
    addopts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"].get("addopts", "")
    addopts = " ".join(addopts) if isinstance(addopts, list) else addopts
    assert not re.search(r"(^|\s)(-k|-m|--deselect|--ignore)\b", addopts), addopts


def test_the_acceptance_map_names_exactly_the_cases_in_005():
    spec = (ROOT / "000-docs/005-AT-DSGN-technical-spec.md").read_text()
    planned = sorted(set(re.findall(r"^\| (TEST-S1-\d\d) \|", spec, flags=re.M)))
    assert planned == sorted(acceptance.CASES) and len(planned) == 22


def test_the_p2_acceptance_map_names_exactly_the_cases_in_016():
    spec = (ROOT / "000-docs/016-AT-DSGN-p2-correspondence-specification.md").read_text()
    planned = sorted(set(re.findall(r"^\| (TEST-P2-\d\d) \|", spec, flags=re.M)))
    assert planned == sorted(acceptance.P2_CASES) and len(planned) == 54


def test_the_p3_acceptance_map_names_exactly_the_cases_in_018():
    spec = (ROOT / "000-docs/018-AT-DSGN-p3-evidence-assessment-specification.md").read_text()
    planned = sorted(set(re.findall(r"^\| (TEST-P3-\d\d) \|", spec, flags=re.M)))
    assert planned == sorted(acceptance.P3_CASES) and len(planned) == 57


def test_the_p4_acceptance_map_names_exactly_the_cases_in_021():
    spec = (ROOT / "000-docs/021-AT-DSGN-p4-agreements-specification.md").read_text()
    planned = sorted(set(re.findall(r"^\| (TEST-P4-\d\d) \|", spec, flags=re.M)))
    assert planned == sorted(acceptance.P4_CASES) and len(planned) == 32


def test_the_p5_acceptance_map_names_exactly_the_cases_in_023():
    spec = (ROOT / "000-docs/023-AT-DSGN-p5-provisioning-specification.md").read_text()
    planned = sorted(set(re.findall(r"^\| (TEST-P5-\d\d) \|", spec, flags=re.M)))
    assert planned == sorted(acceptance.P5_CASES) and len(planned) == 24


def test_every_p5_test_is_mapped():
    """Nothing in the P5 files sits outside the gate: each test is a case or a named P5 design rule."""
    mapped = {name.split("[", 1)[0] for names in {**acceptance.P5_CASES, **acceptance.P5_SUPPORTING}.values()
              for name in names}
    found = set()
    for module in ("test_provisioning", "test_credentials", "test_closure", "test_provisioning_screen",
                   "test_p5_journey"):
        found |= {f"{module}::{n}" for n in re.findall(r"^def (test_\w+)", (ROOT / f"tests/{module}.py").read_text(),
                                                       flags=re.M)}
    assert sorted(found - mapped) == [] and sorted(mapped - found) == []



def test_the_p6_acceptance_map_names_exactly_the_cases_in_026():
    """Every staging case is either gated here or shown only live, never both and never neither."""
    spec = (ROOT / "000-docs/026-AT-DSGN-p6-staging-deployment-specification.md").read_text()
    plan = spec[spec.index("\n## 11. "):spec.index("\n## 12. ")]  # the plan itself, not the status tables in 16
    planned = re.findall(r"^\| (TEST-P6-\d\d) \|", plan, flags=re.M)
    assert planned == [f"TEST-P6-{n:02d}" for n in range(1, 39)]
    assert not set(acceptance.P6_CASES) & set(acceptance.P6_LIVE_ONLY)
    assert sorted({*acceptance.P6_CASES, *acceptance.P6_LIVE_ONLY}) == planned
    for case, script in acceptance.P6_LIVE_ONLY.items():
        assert case in (ROOT / script.split(",")[0]).read_text(), case  # the script names the case it shows


def test_the_evidence_register_names_known_proofs_scripts_beads_and_boundaries_for_every_p6_case():
    """9kg.44: the register is data the report reads. Every numbered case has an entry (defaults are pytest, full,
    GATE-STAGING); every proof type, drill script and residual bead is known; a partial case names what is not yet
    shown and the boundary its residual bead blocks; a live-only case has no pytest proof; the shape-only cases
    are exactly those 028 section 4 names."""
    cases = sorted({*acceptance.P6_CASES, *acceptance.P6_LIVE_ONLY})
    assert set(acceptance.P6_EVIDENCE) == set(cases)  # an explicit entry per case, no optimistic default
    assert acceptance.check_register() == []
    for script, drill in acceptance.DRILLS.items():
        assert (ROOT / script).is_file() and acceptance.REVISION.match(drill["revision"]) and drill["record"], script
    for bead in acceptance.RESIDUAL_BOUNDARIES:
        assert re.fullmatch(r"9kg\.\d+(\.\d+)?", bead)
    used = set()
    for case in cases:
        row = acceptance.evidence(case)
        assert row["proofs"] and all(p["type"] in acceptance.PROOF_TYPES for p in row["proofs"]), case
        for proof in row["proofs"]:
            assert proof["where"] and proof["environment"] and proof["record"], (case, proof)
            if proof["type"] != "pytest":
                assert acceptance.REVISION.match(proof["revision"]), (case, proof)  # a commit or a run id
            else:
                assert proof["revision"] == "this run"
        assert (row["pytest"] is None) == (case in acceptance.P6_LIVE_ONLY), case
        if row["partial"]:
            used.add(row["partial"])
            assert row["residual"] and row["boundary"] == acceptance.RESIDUAL_BOUNDARIES[row["partial"]], case
        else:
            assert row["residual"] is None and row["boundary"] == "GATE-STAGING", case
    assert used == set(acceptance.RESIDUAL_BOUNDARIES)  # no stale or unused residual bead
    # 9kg.64: the stand-in is the cutover drill's environment; the pytest proof ran where every pytest proof runs.
    cutover, pytest_proof = acceptance.evidence("TEST-P6-26")["proofs"]
    assert (cutover["type"], cutover["where"]) == ("drill", "scripts/cutover_rehearsal.sh")
    assert cutover["environment"] == "a stand-in Learn site beside the staging stack on the dev box"
    assert pytest_proof["type"] == "pytest" and pytest_proof["environment"] == acceptance.TEST_ENVIRONMENT
    assert "environment" not in acceptance.P6_EVIDENCE["TEST-P6-26"]  # no entry-level override left to misapply
    shape = [c for c in cases if acceptance.evidence(c)["pytest"] == "shape"]
    assert shape == ["TEST-P6-08", "TEST-P6-24", "TEST-P6-25", "TEST-P6-26", "TEST-P6-31"]
    # Every partial case's pytest evidence, where it has any, is still gated: a partial case is never exempt.
    assert all(c in acceptance.P6_CASES for c in cases if acceptance.evidence(c)["partial"] and acceptance.evidence(c)["pytest"])


def test_the_evidence_register_refuses_optimistic_defaults(monkeypatch):
    """A case with no entry, an unknown drill, a partial case without its residual, a residual bead with no boundary
    and a proof with no commit or run id are refused as data, never filled in."""
    monkeypatch.setattr(acceptance, "P6_EVIDENCE", {**acceptance.P6_EVIDENCE})
    del acceptance.P6_EVIDENCE["TEST-P6-03"]
    assert [p for p in acceptance.check_register() if "TEST-P6-03" in p] == ["TEST-P6-03: no evidence register entry"]
    for entry, message in (
            ({"proofs": [("drill", "scripts/nope.sh")]}, "unknown drill script"),
            ({"proofs": [("drill", "scripts/deploy_drill.sh", "")]}, "at most its own environment"),
            ({"proofs": [("drill", "scripts/deploy_drill.sh", "a", "b")]}, "at most its own environment"),
            ({"partial": "9kg.27"}, "partial without a residual"),
            ({"partial": "9kg.999", "residual": "x"}, "has no boundary"),
            ({"proofs": [("inspected", "a run")]}, "needs a commit or run id"),
            ({"proofs": [("inspected", "a run", "not-a-sha", "record")]}, "needs a commit or run id"),
            ({"proofs": [("walk", "x", "178da42", "r")]}, "unknown proof type"),
            ({"proofs": []}, "no proofs")):
        acceptance.P6_EVIDENCE["TEST-P6-03"] = entry
        with pytest.raises(acceptance.RegisterError, match=message):
            acceptance.evidence("TEST-P6-03")
        assert any("TEST-P6-03" in p for p in acceptance.check_register())
    acceptance.P6_EVIDENCE["TEST-P6-03"] = {"proofs": [("drill", "scripts/staging_check.sh")]}  # a gated case without pytest
    assert "TEST-P6-03: a live-only case has no pytest proof and a gated case has one" in acceptance.check_register()


def test_the_evidence_register_reproduces_aar_028_per_case_and_in_total():
    """The register says, per case, what after-action report 028 section 4 recorded (21 proven, one on a stand-in,
    and 17 partly) unless the entry carries a `since_028` note naming the bead and pull request that moved it; so the
    AAR stays historical and the register and the report can only drift apart deliberately."""
    aar = (ROOT / "000-docs/000-aars/028-AA-AACR-p6-staging.md").read_text()
    table = aar[aar.index("\n## 4. "):aar.index("\n## 5. ")]
    recorded = dict(re.findall(r"^\| (TEST-P6-\d\d) \| (proven on a stand-in|proven|partly) \|", table, flags=re.M))
    assert len(recorded) == 38
    assert [c for c, s in recorded.items() if s == "proven on a stand-in"] == ["TEST-P6-26"]
    assert "stand-in" in acceptance.evidence("TEST-P6-26")["note"]
    at_028 = {case: "partial" if status == "partly" else "full" for case, status in recorded.items()}
    assert (list(at_028.values()).count("full"), list(at_028.values()).count("partial")) == (21, 17)
    moved = {}
    for case, completeness in at_028.items():
        row = acceptance.evidence(case)
        note = acceptance.P6_EVIDENCE[case].get("since_028")
        if row["completeness"] != completeness:
            assert note and re.search(r"9kg\.\d+ \(PR #\d+\)", note), f"{case}: {completeness} in 028, {row['completeness']} here"
            moved[case] = note
        else:
            assert not note, f"{case}: a since_028 note on a case that did not move"
    # Batch 2 (PR #84) moved 10, 24 and 25 to full; 25 was partial against 9kg.63 while the deploy drill submitted
    # without an invitation under the invitation-only default (PR #85), and is full again since the drill invites
    # before each submission and ran 60 of 60 (026 section 16, the 9kg.63 record).
    assert sorted(moved) == ["TEST-P6-10", "TEST-P6-24", "TEST-P6-25"]
    summary = acceptance.summarise(acceptance.register({c: "PASS" for c in acceptance.P6_CASES}))
    assert (summary["full"], summary["partial"], summary["live_only"]) == (24, 14, ["TEST-P6-27"])
    # 24 full, less the live-only case (recorded, never a pytest result) and the four full shape-only cases (08, 24,
    # 25, 26): 25 moved back to full adds no proven case, since its gated tests pin the shape and the drill shows it.
    assert summary["proven_this_run"] == 19
    # A partial case is never proven, whatever its gate result, and a failed full case is not proven either.
    rows = acceptance.register({c: "PASS" if c != "TEST-P6-02" else "FAIL" for c in acceptance.P6_CASES})
    assert acceptance.summarise(rows)["proven_this_run"] == 18
    assert not any(r["proven_this_run"] for r in rows if r["partial"])


REGISTER_PROBE_CONFTEST = """
from tests import acceptance
acceptance.CASES = {}
acceptance.SUPPORTING = {}
acceptance.P2_CASES = {}
acceptance.P3_CASES = {}
acceptance.P3_SUPPORTING = {}
acceptance.P4_CASES = {}
acceptance.P4_SUPPORTING = {}
acceptance.P5_CASES = {}
acceptance.P5_SUPPORTING = {}
acceptance.P6_CASES = {"TEST-P6-01": ["test_probe::test_ran"], "TEST-P6-02": ["test_probe::test_other"]}
acceptance.P6_SUPPORTING = {"a design rule": ["test_probe::test_ran"]}
acceptance.P6_LIVE_ONLY = {"TEST-P6-03": "scripts/staging_check.sh"}
acceptance.P6_EVIDENCE = {
    "TEST-P6-01": {"proofs": [("drill", "scripts/deploy_drill.sh"), "pytest"], "pytest": "shape", "partial": "9kg.28",
                   "residual": "the rest"},
    "TEST-P6-02": {},
    "TEST-P6-03": {"proofs": [("drill", "scripts/staging_check.sh")]},
}
%s
"""


def test_the_report_prints_the_register_and_counts_partial_live_only_and_supporting_apart_from_pass(tmp_path):
    """The report shape (9kg.44): numbered cases are counted apart from supporting groups; a live-only case is
    printed as LIVE ONLY, never as a pytest result; a partial case shows its residual bead and boundary; the
    register totals say full, partial and proven-this-run separately."""
    register_file = tmp_path / "out" / "register.json"
    register_file.parent.mkdir()
    (tmp_path / "conftest.py").write_text(REGISTER_PROBE_CONFTEST % "")
    (tmp_path / "test_probe.py").write_text("def test_ran():\n    assert True\n\ndef test_other():\n    assert True\n")
    # 9kg.64: scripts/test.sh stamps CATALYST_RUN_COMMIT from git; it wins over CI's GITHUB_SHA.
    env = support.child_env(PYTHONPATH=str(ROOT), CATALYST_EVIDENCE_REGISTER=str(register_file),
                            CATALYST_RUN_COMMIT="e" * 40, GITHUB_SHA="f" * 40)
    result = subprocess.run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    out = result.stdout
    assert result.returncode == 0, out
    printed = out.splitlines()
    lines = {line.split()[0]: line for line in printed if line.startswith(("TEST-P6-", "a design", "numbered", "evidence", "shape", "run commit"))}
    assert lines["run"] == "run commit: " + "e" * 40  # the header stamps the run's commit
    assert "PASS" in lines["TEST-P6-01"] and "[drill,pytest:shape; partial->9kg.28; up to the dark deploy (9kg.31.5)]" in lines["TEST-P6-01"]
    assert printed[printed.index(lines["TEST-P6-01"]) + 1] == (
        "    drill@staging stack on the dev box/74cbb53; pytest@test containers (CI and scripts/test.sh)/this run; residual: the rest")
    assert "[pytest:behaviour; full; up to GATE-STAGING]" in lines["TEST-P6-02"]
    assert printed[printed.index(lines["TEST-P6-02"]) + 1] == "    pytest@test containers (CI and scripts/test.sh)/this run"
    assert "LIVE ONLY" in lines["TEST-P6-03"] and "no pytest evidence" in lines["TEST-P6-03"] and "PASS" not in lines["TEST-P6-03"]
    assert "[drill; full; up to GATE-STAGING]" in lines["TEST-P6-03"]
    assert printed[printed.index(lines["TEST-P6-03"]) + 1] == "    drill@staging stack on the dev box/a5a19fd"
    assert "numbered cases: PASS 2, FAIL 0, INCOMPLETE 0, NOT RUN 0; supporting groups: PASS 1, FAIL 0, INCOMPLETE 0, NOT RUN 0; live-only 1 (not a pytest result) (full run: GATE-STAGING requires every case PASS)" in lines["numbered"]
    assert lines["evidence"] == ("evidence register: full 2 (proven by this run 1, of which shape-only are excluded: 1 shape-only, "
                                 "1 live-only recorded), partial 1 (residual beads: 9kg.28 (01))")
    assert lines["shape-only"] == "shape-only pytest evidence (behaviour shown by a drill): TEST-P6-01; live-only: TEST-P6-03"
    # register.json, written at the end of the full run: rows, commit, digest when known, each proof's record pointer.
    written = json.loads(register_file.read_text())
    assert written["commit"] == "e" * 40 and written["image_digest"] is None and written["gate"] == "GATE-STAGING"
    # 9kg.64: the run as it ended, not a row list alone: its exit status, the supporting groups and every gate's counts.
    assert written["exit_status"] == 0 and written["supporting"] == {"a design rule": "PASS"}
    assert written["gates"]["GATE-STAGING"] == {"numbered": {"PASS": 2, "FAIL": 0, "INCOMPLETE": 0, "NOT RUN": 0},
                                                "supporting": {"PASS": 1, "FAIL": 0, "INCOMPLETE": 0, "NOT RUN": 0}}
    assert set(written["gates"]) == {"GATE-S1", "GATE-P2", "GATE-P3", "GATE-P4", "GATE-P5", "GATE-STAGING"}
    assert [r["case"] for r in written["rows"]] == ["TEST-P6-01", "TEST-P6-02", "TEST-P6-03"]
    assert written["rows"][0]["proofs"][0]["record"].startswith("026 section 16") and written["rows"][0]["result"] == "PASS"
    assert written["rows"][2]["result"] == "LIVE ONLY" and written["summary"]["proven_this_run"] == 1
    # A full run whose case fails writes its own register, with that exit status and the case's FAIL: never the
    # earlier green file.
    (tmp_path / "test_probe.py").write_text("def test_ran():\n    assert True\n\ndef test_other():\n    assert False\n")
    failing = subprocess.run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider"],
                             cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert failing.returncode == 1, failing.stdout
    written = json.loads(register_file.read_text())
    assert written["exit_status"] == 1 and [r["result"] for r in written["rows"]] == ["PASS", "FAIL", "LIVE ONLY"]
    assert written["gates"]["GATE-STAGING"]["numbered"]["FAIL"] == 1 and written["summary"]["proven_this_run"] == 0
    # A full run with a broken register (an entry missing) fails the run and writes nothing; the file the earlier run
    # left is deleted at the start, so no stale register survives a refused run (9kg.64).
    assert register_file.exists()
    (tmp_path / "test_probe.py").write_text("def test_ran():\n    assert True\n\ndef test_other():\n    assert True\n")
    (tmp_path / "conftest.py").write_text(REGISTER_PROBE_CONFTEST % 'del acceptance.P6_EVIDENCE["TEST-P6-02"]')
    broken = subprocess.run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert broken.returncode == 1 and "FAILED GATE: evidence register: TEST-P6-02: no evidence register entry" in broken.stdout
    assert "2 passed" in broken.stdout and not register_file.exists()
    # A selected subset neither deletes nor writes it.
    register_file.write_text("{}")
    subset = subprocess.run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider",
                             "test_probe.py"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert subset.returncode == 0, subset.stdout
    assert register_file.read_text() == "{}"


def test_the_run_commit_is_stamped_by_test_sh_and_ci_keeps_the_register_as_a_pinned_artifact():
    """9kg.64: local runs record the commit too (the test image has no git): scripts/test.sh exports it from the
    host's git and compose.yaml passes it to the test service; CI uploads register.json whatever the result, through
    an action pinned by commit like every other, without touching the test command or the job names."""
    test_sh = (ROOT / "scripts/test.sh").read_text()
    assert 'CATALYST_RUN_COMMIT="$(git rev-parse HEAD 2>/dev/null)"' in test_sh and "export CATALYST_RUN_COMMIT" in test_sh
    assert test_sh.index("export CATALYST_RUN_COMMIT") < test_sh.index('"${COMPOSE[@]}" run --rm test')
    compose = (ROOT / "compose.yaml").read_text()
    assert 'CATALYST_RUN_COMMIT: "${CATALYST_RUN_COMMIT:-unrecorded}"' in compose
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    for uses in re.findall(r"uses: (\S+)", ci):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", uses), uses
    runtime = ci[ci.index("\n  runtime:\n"):ci.index("\n  docs:\n")]
    tests_step = runtime.index("- name: Test suite (PostgreSQL)")
    upload = runtime[runtime.index("- name: Keep the evidence register (register.json)"):]
    assert tests_step < runtime.index("- name: Keep the evidence register (register.json)")
    assert "if: ${{ always() }}" in upload and "uses: actions/upload-artifact@" in upload and "path: register.json" in upload


def test_every_p6_test_is_mapped():
    """Every test written for P6 (the files that hold only P6 tests, and the 6b, 9kg and p6 tests in shared files) is
    a staging case, a named P6 design rule, or already part of an earlier gate."""
    p6_files = ("test_web_security", "test_health", "test_system_health", "test_image", "test_backup_commands",
                "test_post_restore", "test_restore_rehearsal", "test_staging_proxy", "test_staff_two_factor",
                "test_fetcher_role", "test_staging_compose", "test_release", "test_secret_rotation", "test_egress",
                "test_staging_alerts", "test_cutover",
                # PR #87 (029 section 13.3 batch item 3): every test of the four new files is a named design rule
                "test_staff_roles", "test_hold_and_resend", "test_human_only", "test_agreement_screens",
                # 9kg.41: the walkthrough file
                "test_screen_walkthrough")
    found = set()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        pattern = r"^(?:async )?def (test_\w+)" if path.stem in p6_files else r"^(?:async )?def (test_(?:6b|9kg|p6|oc4)\w*)"
        found |= {f"{path.stem}::{n}" for n in re.findall(pattern, path.read_text(), flags=re.M)}
    earlier = {name.split("[", 1)[0] for _, gate, cases, supporting in acceptance.gates() if gate != "GATE-STAGING"
               for names in (*cases.values(), *supporting.values()) for name in names}
    p6 = {name.split("[", 1)[0] for names in {**acceptance.P6_CASES, **acceptance.P6_SUPPORTING}.values()
          for name in names}
    assert sorted(found - p6 - earlier) == []
    # A test named for a 6B task or P6 is gated here, never only in an earlier gate; only the 9kg hardening tests
    # that came before P6 may live in an earlier gate alone.
    assert sorted(n for n in found - p6 if re.search(r"::test_(6b|p6)", n)) == []


def test_every_mapped_test_exists():
    missing = []
    for names in acceptance.groups().values():
        assert names
        for name in names:
            module, function = name.split("::")
            function = function.split("[", 1)[0]  # an instance is checked by the full-run gate
            if not function.startswith("test_") or not callable(getattr(importlib.import_module(f"tests.{module}"), function, None)):
                missing.append(name)
    assert missing == []


@pytest.mark.parametrize(("outcomes", "status"), [
    ({"a": {"passed"}, "b": {"passed"}}, "PASS"),
    ({"a": {"passed"}, "b": {"passed", "failed"}}, "FAIL"),  # one parametrized instance failed
    ({"a": {"passed"}}, "INCOMPLETE"),
    ({}, "NOT RUN"),
])
def test_a_case_is_pass_only_when_every_one_of_its_tests_ran_and_passed(outcomes, status):
    assert case_status(["a", "b"], outcomes) == status


def test_the_keys_name_the_function_and_the_instance():
    nodeid = "tests/test_intake.py::test_email_key[ada@example.test-ada@example.test]"
    assert acceptance.key(nodeid) == "test_intake::test_email_key"
    assert acceptance.instance_key(nodeid) == "test_intake::test_email_key[ada@example.test-ada@example.test]"
