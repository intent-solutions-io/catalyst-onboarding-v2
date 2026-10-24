"""Test harness: network protection, the application-role switch and the privileged reset.

Database roles (D-21). pytest-django creates and migrates this run's test database as the migration
owner. django_db_setup below then stamps the database with this run's identity marker and switches the
Django connection to the restricted application role, so every ORM and test-client operation in the
suite runs as `catalyst_app` with all grants, constraints and protection triggers in force. Ordinary tests
roll back (pytest-django's default). Tests that commit through real transactions use `privileged_reset`:
after the test body it closes the connections and joins the threads it handed out, then a dedicated owner
connection, after verifying this run's database identity, disables only the named `catalyst_no_truncate`
triggers, truncates the slice tables, re-enables them and verifies the trigger set and the role
privileges against the session baseline. Any failure raises, so the test errors and the run fails. There
is no bypass in the trigger functions and no session_replication_role switch.

Network protection (TEST-S1-14), at Python level and nothing more.

An autouse fixture patches ``socket.socket.connect`` and ``connect_ex`` for the duration of each test
function, allowing only loopback, Unix sockets and the configured database host. It is a test aid, not
a firewall or sandbox. It does not cover:

- native libraries that open sockets themselves (libpq, used by psycopg's binary wheel);
- code that runs outside a test function (collection, imports, session-scoped fixtures);
- child processes (each subprocess is a fresh interpreter without the patch);
- other socket operations (UDP sendto, DNS resolution).

The container-level boundary is the explicit, synthetic environment the test service receives
(compose.yaml) and config.guards, which refuses provider credentials at start-up."""

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid

import psycopg
import pytest
from psycopg import sql

from tests import acceptance

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _allowed_hosts() -> set[str]:
    db_host = os.environ.get("CATALYST_DB_HOST", "")
    allowed = {"localhost", db_host}
    try:
        allowed.update(info[4][0] for info in socket.getaddrinfo(db_host, None))
    except OSError:
        pass
    return allowed


def _check_destination(sock, address):
    """Raise for a blocked destination; return silently for an allowed one."""
    if sock.family == socket.AF_UNIX:
        return
    host = address[0]
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    if host in _allowed_hosts():
        return
    raise RuntimeError(f"network access blocked in tests: {host}")


def _guarded_connect(self, address):
    _check_destination(self, address)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    _check_destination(self, address)
    return _real_connect_ex(self, address)  # keeps connect_ex semantics (errno, not exceptions)


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)


@pytest.fixture(autouse=True)
def effect_journal(tmp_path, monkeypatch, settings):
    """9kg.33: every test gets its own effect journal (workflow.journal), for this process and the child processes
    it starts (the worker, the owner-run commands), so journaled effects are durable and the post-restore step has
    evidence to read. Returns the directory."""
    directory = tmp_path / "effects"
    directory.mkdir(mode=0o700)
    settings.CATALYST_EFFECT_JOURNAL_DIR = str(directory)
    monkeypatch.setenv("CATALYST_EFFECT_JOURNAL_DIR", str(directory))
    from workflow import journal

    journal._state.usage_cache = None
    return directory


# The public entry's shipped defaults are invitation-only intake and small synthetic limits (9kg.43, 9kg.29;
# config/settings.py). The suite's journeys submit the public form freely from one test client, so each test starts
# with the mode open and every limit far above any burst a journey makes; tests/test_invitation.py and
# tests/test_throttle.py set the values they prove, and the shipped defaults are checked from a fresh process there.
SUITE_PUBLIC_ENTRY = {
    "CATALYST_INTAKE_MODE": "open",
    **{name: 100_000 for name in ("CATALYST_THROTTLE_INTAKE_PER_CLIENT", "CATALYST_THROTTLE_INTAKE_PER_ADDRESS",
                                  "CATALYST_THROTTLE_LINK_PER_CLIENT", "CATALYST_THROTTLE_LINK_PER_TOKEN",
                                  "CATALYST_THROTTLE_WEBHOOK_PER_CLIENT")},
}


@pytest.fixture(autouse=True)
def suite_public_entry(settings):
    for name, value in SUITE_PUBLIC_ENTRY.items():
        setattr(settings, name, value)


# PASS means executed and passed. A skipped test, an expected failure (xfail) or an unexpected pass of
# an xfail-marked test (xpass) cannot satisfy a required case, so any of them fails the run (CI gate).
# Counted from the reports themselves, so it does not depend on the terminal reporter plugin.
_skipped = []


def pytest_runtest_logreport(report):
    if report.skipped or hasattr(report, "wasxfail"):
        _skipped.append(report.nodeid)
    if report.failed or (report.when == "call" and report.passed):
        for name in {acceptance.key(report.nodeid), acceptance.instance_key(report.nodeid)}:
            _acceptance["outcomes"].setdefault(name, set()).add(report.outcome)


def pytest_collectreport(report):
    if report.skipped:
        _skipped.append(report.nodeid)


# The acceptance report (005 S1.7 and 016 section 7, tests/acceptance.py): every case's status at the end of
# the run. A full run (no file, -k or -m selection, nothing deselected) fails unless every case is PASS: that
# is GATE-S1's, GATE-P2's, GATE-P3's, GATE-P4's and GATE-P5's "every case PASS at one head", enforced wherever the whole suite runs (CI and
# scripts/test.sh).
_acceptance = {"outcomes": {}, "deselected": False, "statuses": {}, "full": False}


def pytest_deselected(items):
    _acceptance["deselected"] = True


def case_status(names, outcomes):
    seen = [outcomes.get(name, set()) for name in names]
    if any("failed" in o for o in seen):
        return "FAIL"
    if all(o == {"passed"} for o in seen):
        return "PASS"
    return "NOT RUN" if not any(seen) else "INCOMPLETE"


def _may_be_full(config) -> bool:
    """Whether this run can be a full run: no file, -k or -m selection (deselection is known only after collection)."""
    return config.args_source != pytest.Config.ArgsSource.ARGS and not config.option.keyword and not config.option.markexpr


def pytest_sessionstart(session):
    # 9kg.64: a run that may be full removes the last register.json first, so a run that is refused, fails before the
    # end or turns out not to be full can never leave an earlier run's file behind as if it were its own.
    if _may_be_full(session.config):
        try:
            os.remove(register_path())
        except FileNotFoundError:
            pass


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    outcomes = _acceptance["outcomes"]
    groups = acceptance.groups()
    _acceptance["statuses"] = {case: case_status(names, outcomes) for case, names in groups.items()}
    mapped = {name for names in groups.values() for name in names}
    _acceptance["full"] = _may_be_full(config) and not _acceptance["deselected"] and bool(mapped & outcomes.keys())
    if session.exitstatus == 0 and (_skipped or (_acceptance["full"] and set(_acceptance["statuses"].values()) != {"PASS"})):
        session.exitstatus = 1
    # 9kg.44: the register is checked as data in a full run, and written for the go/no-go package.
    _acceptance["register_problems"] = acceptance.check_register() if _acceptance["full"] else []
    if _acceptance["full"] and _acceptance["register_problems"] and session.exitstatus == 0:
        session.exitstatus = 1
    if _acceptance["full"] and not _acceptance["register_problems"]:
        write_register(_acceptance["statuses"], int(session.exitstatus))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_commit() -> str:
    """The commit this run tests: the one scripts/test.sh stamps from the host's git (CATALYST_RUN_COMMIT, passed by
    compose.yaml; the test image has no git), else CI's, else git's, else unrecorded."""
    for name in ("CATALYST_RUN_COMMIT", "GITHUB_SHA"):
        if os.environ.get(name):
            return os.environ[name]
    if shutil.which("git"):
        probe = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        if probe.returncode == 0:
            return probe.stdout.strip()
    return "unrecorded"


def register_path() -> str:
    return os.environ.get("CATALYST_EVIDENCE_REGISTER") or os.path.join(ROOT, "register.json")


def write_register(statuses, exit_status: int) -> str:
    """register.json (CATALYST_EVIDENCE_REGISTER, or the repository root): the rows, this run's commit, exit status
    and image digest when known, each proof's record pointer, the summary, GATE-STAGING's supporting groups and every
    gate's counts, so the go/no-go package reads the run as it ended rather than a green row list alone (9kg.64)."""
    rows = acceptance.register(statuses)
    gates = {}
    for _, gate, cases, supporting in acceptance.gates():
        gates[gate] = {kind: {s: [statuses[g] for g in groups].count(s) for s in ("PASS", "FAIL", "INCOMPLETE", "NOT RUN")}
                       for kind, groups in (("numbered", cases), ("supporting", supporting))}
    path = register_path()
    # Written beside the target and moved into place (PR #95 review), so a reader never sees a half-written file.
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as out:
        json.dump({"gate": "GATE-STAGING", "commit": run_commit(), "exit_status": exit_status,
                   "image_digest": os.environ.get("CATALYST_IMAGE") or None,
                   "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows,
                   "summary": acceptance.summarise(rows),
                   "supporting": {group: statuses[group] for group in acceptance.P6_SUPPORTING},
                   "gates": gates}, out, indent=1, sort_keys=True)
    os.replace(temporary, path)
    return path


def pytest_terminal_summary(terminalreporter):
    if _skipped:
        terminalreporter.write_line(
            "FAILED GATE: skipped, xfailed or xpassed tests cannot satisfy required cases: " + ", ".join(_skipped),
            red=True,
        )
    statuses = _acceptance["statuses"]
    if not any(s != "NOT RUN" for s in statuses.values()):
        return  # nothing mapped ran (a child probe or an unrelated file): no report
    full = _acceptance["full"]
    for title, gate, cases, supporting in acceptance.gates():
        terminalreporter.section(title)
        register = {}
        if gate == "GATE-STAGING":
            terminalreporter.write_line(f"run commit: {run_commit()}")
            problems = _acceptance.get("register_problems") or ([] if full else acceptance.check_register())
            for problem in problems:
                terminalreporter.write_line(f"FAILED GATE: evidence register: {problem}", red=True)
            if not problems:
                register = {row["case"]: row for row in acceptance.register(statuses)}
        for case in cases:
            terminalreporter.write_line(f"{case:<34} {statuses[case]:<10} {len(cases[case])} mapped tests"
                                        + ("   " + describe_evidence(register[case]) if case in register else ""))
            if case in register:
                terminalreporter.write_line(describe_proofs(register[case]))
        # A live-only case is never a pytest result: it is listed, not counted with PASS (9kg.44).
        for case, row in register.items():
            if row["result"] == "LIVE ONLY":
                terminalreporter.write_line(f"{case:<34} {'LIVE ONLY':<10} no pytest evidence   " + describe_evidence(row))
                terminalreporter.write_line(describe_proofs(row))
        for group in supporting:
            terminalreporter.write_line(f"{group:<34} {statuses[group]:<10} {len(supporting[group])} mapped tests")
        counts = {case: statuses[case] for case in cases}
        summary = "numbered cases: " + ", ".join(f"{s} {list(counts.values()).count(s)}"
                                                 for s in ("PASS", "FAIL", "INCOMPLETE", "NOT RUN"))
        if supporting:
            groups = [statuses[g] for g in supporting]
            summary += "; supporting groups: " + ", ".join(f"{s} {groups.count(s)}" for s in ("PASS", "FAIL", "INCOMPLETE", "NOT RUN"))
        if register:
            summary += f"; live-only {len([r for r in register.values() if r['result'] == 'LIVE ONLY'])} (not a pytest result)"
        scope = f"full run: {gate} requires every case PASS" if full else "selected subset: not gated"
        all_pass = {statuses[g] for g in (*cases, *supporting)} == {"PASS"}
        terminalreporter.write_line(f"{summary} ({scope})", green=full and all_pass)
        if register:
            for line in register_summary(acceptance.summarise(list(register.values()))):
                terminalreporter.write_line(line)


def describe_evidence(row: dict) -> str:
    """One register row as the report prints it: proof types in order, the pytest kind, completeness with the
    residual bead, and the approval boundary (9kg.44)."""
    proofs = ",".join(p["type"] if p["type"] != "pytest" else f"pytest:{row['pytest']}" for p in row["proofs"])
    completeness = f"partial->{row['partial']}" if row["partial"] else "full"
    return f"[{proofs}; {completeness}; up to {row['boundary']}]"


def describe_proofs(row: dict) -> str:
    """The second, indented line: each proof as type@environment/revision, then the residual of a partial case."""
    line = "    " + "; ".join(f"{p['type']}@{p['environment']}/{p['revision']}" for p in row["proofs"])
    if row["partial"]:
        line += f"; residual: {row['residual']}"
    return line


def register_summary(summary: dict) -> list[str]:
    residual = ", ".join(f"{bead} ({', '.join(c.removeprefix('TEST-P6-') for c in cases)})"
                         for bead, cases in sorted(summary["residual"].items()))
    return [
        f"evidence register: full {summary['full']} (proven by this run {summary['proven_this_run']}, of which shape-only "
        f"are excluded: {len(summary['shape_only'])} shape-only, {len(summary['live_only'])} live-only recorded), "
        f"partial {summary['partial']} (residual beads: {residual or 'none'})",
        "shape-only pytest evidence (behaviour shown by a drill): "
        + ", ".join(summary["shape_only"]) + "; live-only: " + ", ".join(summary["live_only"] or ["none"]),
    ]


# --- database roles and the privileged reset (D-21) -----------------------------------------------------

# This run's identity, stamped on its test database. A dict only so the identity probe can tamper with it.
RUN_IDENTITY = {"marker": f"catalyst-test-run:{uuid.uuid4()}"}
# Slice data plus staff accounts, their sessions and the admin log (S1-T7); the read-only group and its
# permissions come from migrations and are kept.
# The agreement types are the P4-D-1 inventory seeded by migration (like the groups), so the reset keeps them.
SLICE_TABLES = re.compile(r"^((applications|workflow|correspondence|assessments|provisioning|erasure)_|agreements_(?!agreementtype$)|accounts_user"
                          r"|django_session$|django_admin_log$|accounts_loginthrottle$|accounts_requestthrottle$|otp_"
                          r"|accounts_staffrolegrant$)")  # 6B.9: throttles and staff devices; 9kg.29; 9kg.30: the grant record
RESET_TRIGGER = "catalyst_no_truncate"
_session = {}


class ResetRefused(RuntimeError):
    pass


@pytest.fixture(scope="session")
def django_db_modify_db_settings(django_db_modify_db_settings_parallel_suffix):
    # A child pytest run (the identity probe) needs its own test database, never the parent's.
    suffix = os.environ.get("CATALYST_TEST_DB_SUFFIX")
    if suffix:
        from django.conf import settings

        if not re.fullmatch(r"[a-z0-9_]{1,20}", suffix):
            raise ValueError("CATALYST_TEST_DB_SUFFIX must be a short lowercase identifier")
        db = settings.DATABASES["default"]
        db.setdefault("TEST", {})["NAME"] = f"test_{db['NAME']}_{suffix}"


def owner_connection():
    """A dedicated owner connection to this run's test database (the owner owns tables; no superuser)."""
    from django.db import connection

    login = _session["owner"]
    return psycopg.connect(
        host=connection.settings_dict["HOST"], port=connection.settings_dict["PORT"],
        dbname=connection.settings_dict["NAME"], user=login["USER"], password=login["PASSWORD"], autocommit=True,
    )


def protection_state(conn):
    """What the reset must leave exactly as it found it: every catalyst_* trigger with its enabled flag, and
    the application and retention roles' privileges on every public table."""
    from django.conf import settings

    roles = settings.CATALYST_DB_ROLES
    triggers = conn.execute(
        "SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
        " WHERE t.tgname LIKE 'catalyst%' AND NOT t.tgisinternal ORDER BY 1, 2"
    ).fetchall()
    privileges = conn.execute(
        "SELECT r.role, t.tablename, has_table_privilege(r.role, t.oid, 'SELECT'), has_table_privilege(r.role, t.oid, 'INSERT'),"
        " has_table_privilege(r.role, t.oid, 'UPDATE'), has_any_column_privilege(r.role, t.oid, 'UPDATE'),"
        " has_table_privilege(r.role, t.oid, 'DELETE'), has_table_privilege(r.role, t.oid, 'TRUNCATE')"
        " FROM (SELECT tablename, ('public.' || quote_ident(tablename))::regclass AS oid FROM pg_tables"
        "       WHERE schemaname = 'public') t CROSS JOIN unnest(%s::text[]) AS r(role) ORDER BY 1, 2",
        [[roles["app"], roles["retention"], roles["backup"], roles["fetcher"]]],
    ).fetchall()
    return triggers, privileges


# The protection the reset must find before it starts and leave behind (003 ADR-14 trigger inventory).
EXPECTED_TRIGGERS = {
    ("applications_submissionversion", "catalyst_append_only"), ("applications_applicationevent", "catalyst_append_only"),
    ("applications_submissionversion", "catalyst_no_truncate"), ("applications_applicationevent", "catalyst_no_truncate"),
    ("applications_retentionaudit", "catalyst_no_truncate"), ("applications_versionadoption", "catalyst_no_truncate"),
    ("applications_retentionaudit", "catalyst_audit_immutable"), ("applications_versionadoption", "catalyst_adoption_immutable"),
    ("assessments_evidencecapture", "catalyst_append_only"), ("assessments_evidencecapture", "catalyst_no_truncate"),  # P3 3B.1
    ("assessments_assessmentrun", "catalyst_run_result_once"),  # P3 3B.2
    ("correspondence_replyinterpretation", "catalyst_interpretation_result_once"),  # P3 3B.3
    ("assessments_qualificationdecision", "catalyst_append_only"), ("assessments_qualificationdecision", "catalyst_no_truncate"),
    ("applications_application", "catalyst_decided_stage_needs_decision"),  # P3 3B.4
    ("workflow_automationpause", "catalyst_restore_hold"),  # 6B.7a
    # 9kg.6: the pause row is cleared only by an audited resume; events carry the inserting transaction
    ("workflow_automationpause", "catalyst_pause_resume_guard"), ("workflow_automationpause", "catalyst_pause_fixed"),
    ("workflow_automationpause", "catalyst_no_truncate"), ("applications_applicationevent", "catalyst_event_txid"),
    ("otp_totp_totpdevice", "catalyst_otp_device_fixed"), ("otp_static_staticdevice", "catalyst_otp_device_fixed"),  # 6B.9
    # 9kg.24: the fetcher's writes, pinned
    ("workflow_pendingaction", "catalyst_fetcher_workflow_pendingaction_insert"),
    ("workflow_pendingaction", "catalyst_fetcher_workflow_pendingaction_update"),
    ("applications_application", "catalyst_fetcher_applications_application_update"),
    ("assessments_evidenceitem", "catalyst_fetcher_assessments_evidenceitem_update"),
    ("applications_applicationevent", "catalyst_fetcher_applications_applicationevent_insert"),
    ("correspondence_staffitem", "catalyst_fetcher_correspondence_staffitem_insert"),
    ("assessments_qualificationdecision", "catalyst_decision_txid"),
    ("agreements_agreementtemplateversion", "catalyst_agreement_template_frozen"),  # P4 4B.1
    ("agreements_agreementtemplateversion", "catalyst_agreement_template_draft"),
    ("agreements_agreementinstance", "catalyst_agreement_instance_insert"),
    ("agreements_agreementinstance", "catalyst_agreement_instance_fixed"),
    ("agreements_agreementrecipient", "catalyst_agreement_recipient_open"),
    ("agreements_agreementrecipient", "catalyst_append_only"), ("agreements_agreementrecipient", "catalyst_no_truncate"),
    ("agreements_providerobservation", "catalyst_append_only"), ("agreements_providerobservation", "catalyst_no_truncate"),  # 4B.2
    ("agreements_providerobservation", "catalyst_observation_txid"),
    ("agreements_agreementinstance", "catalyst_agreement_verified_needs_read"),
    ("agreements_storeddocument", "catalyst_append_only"), ("agreements_storeddocument", "catalyst_no_truncate"),  # 4B.3
    ("agreements_custodyenvelope", "catalyst_append_only"), ("agreements_custodyenvelope", "catalyst_no_truncate"),  # 9kg.34
    ("agreements_documentaccess", "catalyst_append_only"), ("agreements_documentaccess", "catalyst_no_truncate"),
    ("agreements_agreementdetailsversion", "catalyst_agreement_details_frozen"),
    ("agreements_agreementdetailsversion", "catalyst_no_truncate"),
    ("correspondence_staffitemresolution", "catalyst_append_only"),  # 9kg.1
    ("correspondence_staffitemresolution", "catalyst_no_truncate"),
    ("correspondence_inboundmessagelocation", "catalyst_append_only"),
    ("correspondence_inboundmessagelocation", "catalyst_no_truncate"),
    ("correspondence_approvedmessagequestion", "catalyst_append_only"),
    ("correspondence_approvedmessagequestion", "catalyst_no_truncate"),
    ("correspondence_approvedmessage", "catalyst_approved_message_frozen"),
    ("correspondence_approvedmessage", "catalyst_no_truncate"),
    ("correspondence_messagetemplateversion", "catalyst_template_version_frozen"),
    ("correspondence_messagetemplateversion", "catalyst_no_truncate"),
    ("correspondence_inboundmessage", "catalyst_inbound_provenance_frozen"),  # 9kg.5
    ("correspondence_inboundmessage", "catalyst_no_truncate"),
    ("correspondence_outboundmessage", "catalyst_outbound_identity_frozen"),
    ("correspondence_outboundmessage", "catalyst_no_truncate"),
    ("correspondence_questionreplylink", "catalyst_reply_link_identity_frozen"),
    ("correspondence_questionreplylink", "catalyst_no_truncate"),
    ("provisioning_provisioningrequest", "catalyst_provisioning_request_fixed"),  # P5 5B.1
    ("provisioning_addressreservation", "catalyst_provisioning_reservation_fixed"),
    ("provisioning_provisioningattempt", "catalyst_provisioning_attempt_fixed"),
    ("provisioning_provisioningevidence", "catalyst_provisioning_verifier_differs"),
    ("provisioning_provisioningevidence", "catalyst_append_only"),
    ("provisioning_addressreservation", "catalyst_no_truncate"), ("provisioning_provisioningrequest", "catalyst_no_truncate"),
    ("provisioning_provisioningattempt", "catalyst_no_truncate"), ("provisioning_provisioningevidence", "catalyst_no_truncate"),
    ("provisioning_credentialsetup", "catalyst_credential_setup_fixed"),  # P5 5B.2
    ("provisioning_credentialsetup", "catalyst_no_truncate"),
    ("provisioning_accessrevocation", "catalyst_access_revocation_fixed"),  # P5 5B.3
    ("provisioning_withdrawalconfirmation", "catalyst_withdrawal_confirmation_fixed"),
    ("provisioning_accessrevocation", "catalyst_no_truncate"), ("provisioning_withdrawalconfirmation", "catalyst_no_truncate"),
    ("accounts_staffrolegrant", "catalyst_append_only"), ("accounts_staffrolegrant", "catalyst_no_truncate"),  # 9kg.30
    ("applications_invitation", "catalyst_invitation_fixed"), ("applications_invitation", "catalyst_no_truncate"),  # 9kg.43
    ("applications_memberagreementonfile", "catalyst_member_on_file_fixed"),  # 9kg.52
    ("applications_memberagreementonfile", "catalyst_no_truncate"),
    ("erasure_erasureaudit", "catalyst_append_only"), ("erasure_erasureaudit", "catalyst_no_truncate"),  # 9kg.32
    ("erasure_erasureaudit", "catalyst_erasure_audit_txid"),
}


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker, django_db_keepdb):
    from django.conf import settings
    from django.db import connection, connections
    from django.test.utils import setup_databases, teardown_databases

    created = None
    with django_db_blocker.unblock():
        if connection.settings_dict["NAME"] == os.environ["CATALYST_DB_NAME"]:
            # pytest-django creates a test database only when a selected test has the django_db mark; a run of
            # privileged_reset tests alone needs one too. Never stamp or reset the configured database itself.
            created = setup_databases(verbosity=0, interactive=False, aliases={"default"})
        name = connection.settings_dict["NAME"]
        if name == os.environ["CATALYST_DB_NAME"]:
            raise ResetRefused("no test database was created; refusing to use the configured database")
        if django_db_keepdb:
            raise ResetRefused("--reuse-db is not supported: the reset only ever targets a database this run created")
        with connection.cursor() as cursor:
            # A database this run created carries no comment yet; anything else was not created by this run.
            cursor.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = current_database()")
            if cursor.fetchone()[0] is not None:
                raise ResetRefused(f"test database {name!r} already carries an identity marker; refusing to adopt it")
            cursor.execute(f"COMMENT ON DATABASE {connection.ops.quote_name(name)} IS %s", [RUN_IDENTITY["marker"]])
        _session["owner"] = {"USER": connection.settings_dict["USER"], "PASSWORD": connection.settings_dict["PASSWORD"]}
        with owner_connection() as conn:
            _session["baseline"] = protection_state(conn)
        triggers = _session["baseline"][0]
        if {(t, g) for t, g, _ in triggers} != EXPECTED_TRIGGERS or {e for _, _, e in triggers} != {"O"}:
            raise ResetRefused(f"the migrated test database does not hold the expected enabled protection triggers: {triggers}")
        connection.close()
        connection.settings_dict.update(USER=settings.CATALYST_DB_ROLES["app"], PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"])
    yield
    with django_db_blocker.unblock():
        connections.close_all()
    # The test database is dropped as the owner: by pytest-django after this teardown, or here.
    connection.settings_dict.update(_session["owner"])
    if created is not None:
        with django_db_blocker.unblock():
            teardown_databases(created, verbosity=0)


class Committed:
    """Handed to a test by `privileged_reset`: connections and threads it opens are closed and joined before
    the reset, and `reset()` may also be called explicitly."""

    def __init__(self):
        self._connections = []
        self._threads = []

    def connect(self, role_key, autocommit=False):
        from django.conf import settings
        from django.db import connection

        role = settings.CATALYST_DB_ROLES[role_key]
        password = os.environ[f"CATALYST_DB_{role_key.upper()}_PASSWORD"]
        conn = psycopg.connect(
            host=connection.settings_dict["HOST"], port=connection.settings_dict["PORT"],
            dbname=connection.settings_dict["NAME"], user=role, password=password, autocommit=autocommit,
        )
        self._connections.append(conn)
        return conn

    def thread(self, target, *args):
        """A started thread whose Django connections are closed when `target` returns or raises."""
        from django.db import connections

        def body():
            try:
                target(*args)
            finally:
                connections.close_all()

        t = threading.Thread(target=body, daemon=True)
        self._threads.append(t)
        t.start()
        return t

    def release(self):
        from django.db import connection, connections

        # Close the test's own connections first: one may hold a lock a test thread is waiting on.
        for conn in self._connections:
            conn.close()
        self._connections.clear()
        for t in self._threads:
            t.join(timeout=30)
            if t.is_alive():
                raise ResetRefused("a test thread did not finish; reset refused")
        self._threads.clear()
        if connection.in_atomic_block:
            raise ResetRefused("privileged_reset cannot run inside a django_db transaction; drop the django_db mark")
        connections.close_all()

    def reset(self):
        self.release()
        reset_test_database()


def reset_test_database(settle_seconds=5):
    from django.db import connection

    with owner_connection() as conn:
        database, marker = conn.execute(
            "SELECT current_database(), shobj_description(d.oid, 'pg_database') FROM pg_database d"
            " WHERE d.datname = current_database()"
        ).fetchone()
        if database != connection.settings_dict["NAME"] or marker != RUN_IDENTITY["marker"]:
            raise ResetRefused(f"reset refused: database {database!r} does not carry this test run's identity marker")
        # Every other session must be gone (closed above); allow a moment for backends to exit.
        deadline = time.monotonic() + settle_seconds
        while conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()"
        ).fetchone()[0]:
            if time.monotonic() > deadline:
                raise ResetRefused("reset refused: other sessions are still connected to the test database")
            time.sleep(0.05)
        protected = [r[0] for r in conn.execute(
            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE t.tgname = %s ORDER BY 1",
            [RESET_TRIGGER],
        )]
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
                  if SLICE_TABLES.match(r[0])]
        trigger = sql.Identifier(RESET_TRIGGER)
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '5s'")
            for table in protected:
                conn.execute(sql.SQL("ALTER TABLE public.{} DISABLE TRIGGER {}").format(sql.Identifier(table), trigger))
            conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
                sql.SQL(", ").join(sql.SQL("public.{}").format(sql.Identifier(t)) for t in tables)))
            for table in protected:
                conn.execute(sql.SQL("ALTER TABLE public.{} ENABLE TRIGGER {}").format(sql.Identifier(table), trigger))
        if protection_state(conn) != _session["baseline"]:
            raise ResetRefused("reset left the protection triggers or role privileges different from the session baseline")
        leftover = [t for t in tables if conn.execute(
            sql.SQL("SELECT EXISTS (SELECT 1 FROM public.{})").format(sql.Identifier(t))).fetchone()[0]]
        if leftover:
            raise ResetRefused(f"reset left rows in {leftover}")


@pytest.fixture
def privileged_reset(django_db_setup, django_db_blocker):
    """For tests that commit through real transactions (concurrency, committed role tests). Do not combine
    with the django_db mark. The reset runs after the test body, pass or fail."""
    committed = Committed()
    with django_db_blocker.unblock():
        yield committed
        committed.reset()
