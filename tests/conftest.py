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
import os
import re
import socket
import threading
import time
import uuid

import psycopg
import pytest
from psycopg import sql

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


# PASS means executed and passed. A skipped test, an expected failure (xfail) or an unexpected pass of
# an xfail-marked test (xpass) cannot satisfy a required case, so any of them fails the run (CI gate).
# Counted from the reports themselves, so it does not depend on the terminal reporter plugin.
_skipped = []


def pytest_runtest_logreport(report):
    if report.skipped or hasattr(report, "wasxfail"):
        _skipped.append(report.nodeid)


def pytest_collectreport(report):
    if report.skipped:
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    if _skipped and session.exitstatus == 0:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter):
    if _skipped:
        terminalreporter.write_line(
            "FAILED GATE: skipped, xfailed or xpassed tests cannot satisfy required cases: " + ", ".join(_skipped),
            red=True,
        )


# --- database roles and the privileged reset (D-21) -----------------------------------------------------

# This run's identity, stamped on its test database. A dict only so the identity probe can tamper with it.
RUN_IDENTITY = {"marker": f"catalyst-test-run:{uuid.uuid4()}"}
# Slice data plus staff accounts, their sessions and the admin log (S1-T7); the read-only group and its
# permissions come from migrations and are kept.
SLICE_TABLES = re.compile(r"^((applications|workflow|correspondence)_|accounts_user|django_session$|django_admin_log$)")
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
        [[roles["app"], roles["retention"]]],
    ).fetchall()
    return triggers, privileges


# The protection the reset must find before it starts and leave behind (003 ADR-14 trigger inventory).
EXPECTED_TRIGGERS = {
    ("applications_submissionversion", "catalyst_append_only"), ("applications_applicationevent", "catalyst_append_only"),
    ("applications_submissionversion", "catalyst_no_truncate"), ("applications_applicationevent", "catalyst_no_truncate"),
    ("applications_retentionaudit", "catalyst_no_truncate"), ("applications_versionadoption", "catalyst_no_truncate"),
    ("applications_retentionaudit", "catalyst_audit_immutable"), ("applications_versionadoption", "catalyst_adoption_immutable"),
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
