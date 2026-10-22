"""9kg.24 (026 P6-D-14): the evidence fetcher runs as its own narrower database role.

The worker runs everything but `fetch_evidence` as the application role; the fetch runs as the fetcher role, through
the real worker command, so a missing grant fails here."""

import contextlib
import os
from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.models.functions import Now
from psycopg import errors

from applications.models import Application, ApplicationEvent
from assessments.models import AssessmentRun
from config import runtime
from tests.test_evidence import activate, apply, ev, items, source, url  # noqa: F401  (fixture chain and helpers)
from tests.test_outbound import p2  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from workflow.models import PendingAction


def worker(**options):
    call_command("run_worker", exit_when_idle=True, stdout=StringIO(), **options)


@contextlib.contextmanager
def as_fetcher(settings, role_key="fetcher"):
    """This process, declared a worker with CATALYST_PROCESS_ROLE=fetcher, connecting as `role_key`."""
    default = connections["default"]
    saved = (default.settings_dict["USER"], default.settings_dict["PASSWORD"], settings.CATALYST_PROCESS_ROLE,
             runtime._declared["kind"])
    connections.close_all()
    settings.CATALYST_PROCESS_ROLE = "fetcher"
    runtime.declare_process("worker")
    default.settings_dict.update(USER=settings.CATALYST_DB_ROLES[role_key],
                                 PASSWORD=os.environ[f"CATALYST_DB_{role_key.upper()}_PASSWORD"])
    try:
        yield
    finally:
        connections.close_all()
        default.settings_dict.update(USER=saved[0], PASSWORD=saved[1])
        settings.CATALYST_PROCESS_ROLE = saved[2]
        runtime._declared["kind"] = saved[3]


def collect_as_fetcher(env, settings, **claims):
    app = apply(env, **claims)
    activate()
    worker(exclude="fetch_evidence")  # the worker hands the fetches over and never runs one
    assert PendingAction.objects.filter(kind="fetch_evidence", status="queued").exists()
    with as_fetcher(settings):
        worker(only="fetch_evidence")
    app.refresh_from_db()
    return app


def test_9kg24_the_fetcher_role_fetches_completes_collection_and_queues_the_assessment(ev, settings):
    source(ev)
    for n in (1, 2):
        ev.site.page(f"/w{n}", f"<p>Work sample number {n}.</p>")
    app = collect_as_fetcher(ev, settings, work_url_1=url(ev, "/w1"), work_url_2=url(ev, "/w2"))
    assert {i.status for i in items(app)} == {"fetched"}
    assert ApplicationEvent.objects.filter(application=app, kind="evidence_collection_complete").count() == 1
    assert AssessmentRun.objects.filter(application=app).count() == 1
    assert not PendingAction.objects.filter(kind="fetch_evidence", status__in=("queued", "running")).exists()


@pytest.mark.parametrize(("status", "expected"), [(503, ("unavailable", "http_503")), (404, ("fetched", "")),
                                                  (403, ("unavailable", "http_403"))])
def test_9kg24_the_fetcher_role_records_retries_refusals_and_missing_pages(ev, settings, status, expected):
    source(ev)
    ev.site.page("/p", "<p>x</p>", status=status)
    app = collect_as_fetcher(ev, settings, work_url_1=url(ev, "/p"))
    for _ in range(2):  # a retried fetch is run again by the fetcher, never by the worker
        PendingAction.objects.filter(kind="fetch_evidence", status="queued").update(due_at=Now())
        with as_fetcher(settings):
            worker(only="fetch_evidence")
    [item] = items(app)
    assert item.status == expected[0] and (not expected[1] or item.reason_code == expected[1])
    assert Application.objects.get(pk=app.pk).stage == "assessing"


@pytest.mark.parametrize("statement", [
    "SELECT count(*) FROM accounts_user", "SELECT count(*) FROM django_session",
    "SELECT count(*) FROM correspondence_outboundmessage", "SELECT count(*) FROM agreements_agreementinstance",
    "SELECT count(*) FROM provisioning_provisioningrequest", "SELECT count(*) FROM otp_totp_totpdevice",
    "UPDATE applications_applicationevent SET kind = kind", "DELETE FROM assessments_evidencecapture",
    "INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
    " VALUES ('system', gen_random_uuid(), 'x', 'x', now())",
    "UPDATE applications_application SET email = email",
])
def test_9kg24_the_fetcher_role_reaches_nothing_else(p2, statement):
    fetcher = p2.committed.connect("fetcher", autocommit=True)
    with pytest.raises(errors.InsufficientPrivilege):
        fetcher.execute(statement)


def test_9kg24_a_fetcher_process_must_connect_as_the_fetcher_role_and_run_only_the_fetch(p2, settings):
    from django.core.exceptions import ImproperlyConfigured

    with as_fetcher(settings, role_key="app"), pytest.raises(ImproperlyConfigured, match="not the fetcher role"):
        worker(only="fetch_evidence")
    with as_fetcher(settings), pytest.raises(CommandError, match="the fetcher runs only fetch_evidence"):
        worker(only="fetch_evidence,collect")
    with as_fetcher(settings), pytest.raises(CommandError, match="the fetcher runs only fetch_evidence"):
        worker()
    connections.close_all()
    settings.CATALYST_PROCESS_ROLE = ""
    runtime.declare_process("worker")
    default = connections["default"]
    saved = (default.settings_dict["USER"], default.settings_dict["PASSWORD"])
    default.settings_dict.update(USER=settings.CATALYST_DB_ROLES["fetcher"],
                                 PASSWORD=os.environ["CATALYST_DB_FETCHER_PASSWORD"])
    try:
        with pytest.raises(ImproperlyConfigured, match="not the application role"):
            worker()  # an ordinary worker may not borrow the fetcher's login either
    finally:
        connections.close_all()
        default.settings_dict.update(USER=saved[0], PASSWORD=saved[1])
