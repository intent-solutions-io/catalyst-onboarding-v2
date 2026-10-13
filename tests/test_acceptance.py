"""First-slice acceptance (S1-T8; 005 S1.7, GATE-S1): the whole-flow cases TEST-S1-15 and TEST-S1-16, the
parts of TEST-S1-14 and TEST-S1-20 no earlier task covered, and the checks that keep the acceptance map
(tests/acceptance.py) honest.

The flow is always the real one: an intake POST, the real worker command sending to the local sink, the
link read from the sink, the confirmation GET and POST, a later repeat, and staff reading the dossier.
These tests commit (`privileged_reset`), like the worker and staff tests they compose.
"""

import importlib
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

from applications.models import Application, ContactChallenge, SubmissionVersion
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
        assert Client().post(FORM, "x" * (70 * 1024), content_type="application/x-www-form-urlencoded").status_code == 400
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
    declared = {c.name for label in ("applications", "workflow", "correspondence")
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
    assert "TEST-PROBE" in complete.stdout and "PASS 1, FAIL 0, INCOMPLETE 0, NOT RUN 0 (full run" in complete.stdout
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


def test_every_mapped_test_exists():
    missing = []
    for names in {**acceptance.CASES, **acceptance.SUPPORTING}.values():
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
