"""P3 task 3B.1: versioned claims, deterministic fixture-backed evidence collection and staff-visible observations,
without any model call (018 sections 2, 3, 4 steps 1 to 3, 4.1, 7; owner decision D-34). TEST-P3-05, 06, 09 to 20
and 54.

Synthetic only: a scripted HTTPS server on loopback with the synthetic CA, reached through `fixture_only` sources
whose pinned address replaces DNS; every other step of the fetch pipeline is the production one.
"""

import re
from urllib.parse import urlencode

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db.models.functions import Now
from django.test import Client
from django.urls import reverse
from psycopg import errors

from applications.models import Application, ApplicationEvent
from assessments import collection, fetch, services
from assessments.models import EvidenceCapture, EvidenceItem, EvidenceSource
from config import guards
from correspondence.models import StaffItem
from tests.http_fixture import ScriptedHTTPS, slow_drip
from tests.test_inbound import tls  # noqa: F401  (session TLS material)
from tests import support
from tests.test_outbound import p2, run_worker, staff  # noqa: F401
from workflow.models import AutomationPause, PendingAction

HOST, MIRROR, ELSEWHERE = "evidence.example.test", "mirror.example.test", "elsewhere.example.test"
FORM = reverse("applications:request_access")
BASE = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access.", **support.INTAKE_ANSWERS}


@pytest.fixture
def ev(p2, tls, settings):
    """A running fixture site, a source owner and an assessment operator. Sources are defined per test."""
    server = ScriptedHTTPS(tls.evidence).start()
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = [HOST, MIRROR]
    settings.CATALYST_EVIDENCE_FIXTURE_ADDRESS = "127.0.0.1"
    settings.CATALYST_EVIDENCE_CA_FILE = tls.ca
    settings.CATALYST_EVIDENCE_DEADLINE_SECONDS = 5
    settings.CATALYST_EVIDENCE_FETCH_ATTEMPTS = 2
    p2.site = server
    p2.source_owner = staff(p2, "source-owner", "Evidence source owner")
    p2.assessor = staff(p2, "assessor", "Assessment operator")
    p2.operator = staff(p2, "operator", "Correspondence operator")
    yield p2
    server.stop()


def source(env, kind="work_sample_page", host=HOST, approve=True, **kw):
    s = services.define_evidence_source(key=kw.pop("key", f"{kind}-{host}"), kind=kind, host=host, port=env.site.port,
                                        fixture_only=True, max_bytes=kw.pop("max_bytes", 65536),
                                        deadline_seconds=kw.pop("deadline_seconds", 5), **kw)
    return services.approve_evidence_source(s.pk, env.source_owner, s.definition_sha256) if approve else s


def url(env, path, host=HOST):
    return f"https://{host}:{env.site.port}{path}"


def apply(env, **claims):
    """The applicant's own S1 flow with claim fields: intake, the verification mail, the confirmation."""
    data = {**BASE, **claims}
    assert Client().post(FORM, urlencode(data), content_type="application/x-www-form-urlencoded").status_code == 302
    run_worker()
    path = re.search(r"http://catalyst\.example\.test(/confirm/\S+/)", mail.outbox[-1].body).group(1)
    version = re.search(r'name="version" value="([^"]+)"', Client().get(path).content.decode()).group(1)
    assert Client().post(path, {"version": version}).status_code == 200
    return Application.objects.order_by("-id").first()


def activate(**kw):
    from io import StringIO

    out = StringIO()
    call_command("activate_evidence_collection", activation_version=1, approval_ref="D-34", stdout=out, **kw)
    return out.getvalue()


def collect(env, **claims):
    app = apply(env, **claims)
    activate()
    run_worker()
    app.refresh_from_db()
    return app


def items(app):
    return list(EvidenceItem.objects.filter(application=app).order_by("claim_ref", "round"))


# --- claims (018 section 2) --------------------------------------------------------------------------------

def test_claims_are_stored_in_the_adopted_version_and_shown_before_confirmation(ev):
    data = {**BASE, "work_url_1": "https://evidence.example.test/w", "work_note_1": "A synthetic page",
            "contribution": "I wrote the parser.", "cred_name_1": "Synthetic cert", "cred_identifier_1": "ID-1", "no_certifications": ""}
    Client().post(FORM, urlencode(data), content_type="application/x-www-form-urlencoded")
    run_worker()
    path = re.search(r"http://catalyst\.example\.test(/confirm/\S+/)", mail.outbox[-1].body).group(1)
    page = Client().get(path).content.decode()
    assert "I wrote the parser." in page and "https://evidence.example.test/w" in page
    version = Application.objects.get().versions.get()
    claims = version.submitted_fields["claims"]
    assert claims["work"] == [{"url": "https://evidence.example.test/w", "note": "A synthetic page"}]
    assert claims["credentials"][0]["identifier"] == "ID-1" and claims["contribution"] == "I wrote the parser."


def test_a_submission_without_claims_keeps_the_s1_shape_and_http_links_are_refused(ev):
    response = Client().post(FORM, urlencode({**BASE, "work_url_1": "http://evidence.example.test/w"}),
                             content_type="application/x-www-form-urlencoded")
    assert response.status_code == 200 and "https://" in response.content.decode()  # a form error, nothing saved
    Client().post(FORM, urlencode(BASE), content_type="application/x-www-form-urlencoded")
    assert set(Application.objects.get().versions.get().submitted_fields) == {"name", "email", "reason", *support.STORED_ANSWERS}


# --- TEST-P3-09, 10: activation and slots ----------------------------------------------------------------

def test_p3_09_activation_releases_only_eligible_held_rows_with_events(ev):
    source(ev)
    ev.site.page("/w", "<p>A synthetic work page.</p>")
    claimed = apply(ev, work_url_1=url(ev, "/w"))
    bare = apply(ev, email="bob@example.test")  # no claims: an S1-shaped version
    paused = apply(ev, email="cy@example.test", work_url_1=url(ev, "/w"))
    AutomationPause.objects.create(subject_type="application", subject_id=paused.public_ref, reason="synthetic", actor_ref="t")
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="unknown activation version"):
        call_command("activate_evidence_collection", activation_version=2, approval_ref="D-34")
    with pytest.raises(CommandError, match="approval reference"):
        call_command("activate_evidence_collection", activation_version=1, approval_ref="  ")
    assert '"released": 1' in activate(dry_run=True)
    assert PendingAction.objects.filter(kind="start_evidence_collection", status="held").count() == 3  # dry run changed nothing
    report = activate()
    assert '"released": 1' in report and '"claims_missing": 1' in report and '"paused": 1' in report
    assert PendingAction.objects.get(subject_id=claimed.public_ref, kind="start_evidence_collection").status == "queued"
    assert StaffItem.objects.filter(reason_code="claims_missing", application=bare, status="open").count() == 1
    assert ApplicationEvent.objects.get(kind="evidence_collection_activated").data == {"activation_version": 1, "approval_ref": "D-34"}


def test_p3_10_slots_per_claim_and_source_and_a_changed_adoption_is_refused(ev):
    source(ev)
    source(ev, kind="credential_verification")
    ev.site.page("/w", "<p>Work.</p>")
    ev.site.page("/c", "<p>Credential ID-7 is valid.</p>")
    app = collect(ev, work_url_1=url(ev, "/w"), work_url_2=url(ev, "/x", host=ELSEWHERE),
                  cred_name_1="Cert", cred_identifier_1="ID-7", cred_url_1=url(ev, "/c"), no_certifications="")
    work1, work2, cred = (next(i for i in items(app) if i.claim_ref == r) for r in ("work:1", "work:2", "credential:1"))
    assert (work1.status, cred.status) == ("fetched", "fetched")
    assert (work2.status, work2.reason_code) == ("refused", "no_approved_source")  # never a negative finding
    assert cred.captures.get().outcome == "found"
    assert app.stage == "assessing"
    # A changed adoption is refused by the handler.
    other = apply(ev, email="dee@example.test", work_url_1=url(ev, "/w"))
    owner = ev.committed.connect("owner", autocommit=True)  # test setup: the app role cannot rewrite an input
    owner.execute("UPDATE workflow_pendingaction SET status = 'queued', input_ref = %s WHERE subject_id = %s"
                  " AND kind = 'start_evidence_collection'", ["00000000-0000-0000-0000-000000000000", other.public_ref])
    run_worker()
    assert StaffItem.objects.filter(reason_code="adoption_changed", application=other).exists()
    assert Application.objects.get(pk=other.pk).stage == "contact_verified"


# --- TEST-P3-05, 11, 12, 54: hosts and addresses ---------------------------------------------------------

@pytest.mark.parametrize(("address", "allowed"), [
    ("93.184.216.34", True), ("2606:4700::1111", True), ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False),
    ("192.168.1.1", False), ("100.64.0.1", False), ("169.254.169.254", False), ("0.0.0.0", False), ("192.0.0.1", False),
    ("::1", False), ("::", False), ("fc00::1", False), ("fe80::1", False), ("::ffff:127.0.0.1", False),
    ("::ffff:93.184.216.34", True), ("2002:7f00:1::", False), ("2001::1", False), ("64:ff9b::7f00:1", False),
    ("64:ff9b:1::1", False), ("fd00:ec2::254", False), ("224.0.0.1", False), ("not-an-ip", False),
])
def test_p3_11_address_classification(address, allowed):
    assert fetch.classify(address) is allowed


def test_p3_54_classify_has_no_environment_branch_and_fixtures_need_the_test_environment(settings):
    names = set(fetch.classify.__code__.co_names)  # what the function body refers to, not its docstring
    assert not names & {"settings", "environ", "os", "getenv"}
    assert fetch.classify("127.0.0.1", frozenset({"127.0.0.1"})) and not fetch.classify("127.0.0.1")

    class Fake:
        CATALYST_ENV = "development"
        CATALYST_EVIDENCE_ALLOWED_HOSTS = ["x.example.test"]
        CATALYST_EVIDENCE_FIXTURE_ADDRESS = "127.0.0.1"
        CATALYST_EVIDENCE_CA_FILE = "/tmp/ca.pem"
    assert len(guards.evidence_problems(Fake, {})) == 3
    assert guards.evidence_problems(Fake, {"CATALYST_EVIDENCE_ALLOWED_HOSTS": "x"})[0].endswith("environment")


@pytest.mark.parametrize(("value", "code"), [
    ("http://evidence.example.test/w", "scheme_not_https"),
    ("https://user:pw@evidence.example.test/w", "userinfo_refused"),
    ("https://127.0.0.1/w", "host_not_a_name"), ("https://2130706433/w", "host_not_a_name"),
    ("https://0x7f.1/w", "host_not_a_name"), ("https://other.example.test/w", "host_not_allowed"),
    ("https://evidence.example.test:8443/w", "port_not_allowed"),
    ("https://evidence.example.test/%2e%2e/etc", "path_not_allowed"),
    ("https://evidence.example.test/w\\x", "url_characters_refused"),
    ("https://evidence.example.test/" + "a" * 2100, "url_too_long"),
])
def test_p3_05_15_unsafe_urls_are_refused(value, code):
    src = EvidenceSource(host=HOST, port=443, path_prefix="/w")
    with pytest.raises(fetch.Refused, match=code):
        fetch.validate_url(value, src, {HOST})


def test_p3_05_a_host_outside_the_settings_allow_list_is_refused_and_nothing_is_stored(ev, settings):
    source(ev)
    ev.site.page("/w", "<p>Work.</p>")
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = []
    app = collect(ev, work_url_1=url(ev, "/w"))
    [item] = items(app)
    assert (item.status, item.reason_code) == ("refused", "source_not_allowed") and ev.site.requests == []
    assert EvidenceCapture.objects.count() == 0


def test_p3_12_mixed_dns_answers_refuse_and_a_peer_mismatch_sends_nothing(ev, monkeypatch, settings):
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = [HOST, "public.example.test"]
    real = EvidenceSource(host="public.example.test", port=443, path_prefix="/", content_types=["text/html"],
                          max_bytes=1000, deadline_seconds=5, fixture_only=False)
    monkeypatch.setattr(fetch, "resolve", lambda host, port, timeout: ["93.184.216.34", "10.0.0.7"])
    with pytest.raises(fetch.Refused, match="address_not_allowed"):
        fetch.fetch("https://public.example.test/w", real)
    target = fetch.validate_url(url(ev, "/w"), source(ev), {HOST})
    with pytest.raises(fetch.Refused, match="peer_not_allowed"):
        fetch._one_request(target, "127.0.0.1", frozenset({"127.0.0.2"}), source(ev, key="b"), lambda: 5.0)
    assert ev.site.requests == []  # refused before any request byte


# --- TEST-P3-13, 14, 15, 16: redirects, limits, headers --------------------------------------------------

def test_p3_13_redirects_are_revalidated(ev):
    src = source(ev, redirect_hosts=[MIRROR])
    ev.site.page("/w", "", status=302, Location=url(ev, "/m", host=MIRROR))
    ev.site.page("/m", "<p>Mirrored.</p>")
    assert fetch.fetch(url(ev, "/w"), src).status == 200
    ev.site.page("/x", "", status=302, Location=url(ev, "/m", host=ELSEWHERE))
    with pytest.raises(fetch.Refused, match="host_not_allowed"):
        fetch.fetch(url(ev, "/x"), src)
    ev.site.page("/h", "", status=301, Location=f"http://{HOST}/m")
    with pytest.raises(fetch.Refused, match="redirect_not_https"):
        fetch.fetch(url(ev, "/h"), src)
    chain = source(ev, key="chain", redirect_hosts=[HOST])  # same-host redirects too must be listed
    for n in range(5):
        ev.site.page(f"/l{n}", "", status=302, Location=url(ev, f"/l{n + 1}"))
    with pytest.raises(fetch.Refused, match="too_many_redirects"):
        fetch.fetch(url(ev, "/l0"), chain)
    with pytest.raises(fetch.Refused, match="host_not_allowed"):
        fetch.fetch(url(ev, "/l0"), src)  # the source does not list its own host: redirects are off


def test_p3_14_the_byte_cap_truncates_and_the_deadline_stops_a_slow_drip(ev):
    src = source(ev, max_bytes=100)
    ev.site.page("/big", "<p>" + "a" * 5000 + "</p>")
    result = fetch.fetch(url(ev, "/big"), src)
    assert result.truncated and len(result.body) == 100
    assert fetch.sha256(result.body) == fetch.sha256(("<p>" + "a" * 5000 + "</p>").encode()[:100])  # digest of bytes read
    slow = source(ev, key="slow", deadline_seconds=1, content_types=["text/plain"])
    ev.site.routes["/drip"] = slow_drip(0.2, 50)
    with pytest.raises(fetch.Transient):
        fetch.fetch(url(ev, "/drip"), slow)


def test_p3_15_content_type_and_encoding_are_refused_and_refusals_are_not_retried(ev):
    source(ev)
    ev.site.page("/bin", b"\x00\x01", content_type="application/octet-stream")
    ev.site.page("/gz", "<p>x</p>", **{"Content-Encoding": "gzip"})
    app = collect(ev, work_url_1=url(ev, "/bin"), work_url_2=url(ev, "/gz"))
    statuses = {i.claim_ref: (i.status, i.reason_code) for i in items(app)}
    assert statuses == {"work:1": ("refused", "content_type_refused"), "work:2": ("refused", "content_encoding_refused")}
    assert len([r for r in ev.site.requests if r["path"] in ("/bin", "/gz")]) == 2  # one request each: never retried


def test_p3_16_requests_carry_no_cookie_or_credential_and_logs_hold_no_path(ev, caplog):
    source(ev)
    ev.site.page("/secret-path", "<p>Work.</p>")
    collect(ev, work_url_1=url(ev, "/secret-path?token=abc"))
    [request] = [r for r in ev.site.requests if r["path"].startswith("/secret-path")]
    headers = {k.lower() for k in request["headers"]}
    assert not headers & {"cookie", "authorization", "proxy-authorization"}
    assert request["headers"]["Accept-Encoding"] == "identity"
    assert "secret-path" not in caplog.text and "token=abc" not in caplog.text


# --- TEST-P3-06, 17, 18, 19, 20: outcomes, immutability, completion ---------------------------------------

def test_p3_06_18_a_transient_failure_retries_then_is_unavailable_never_a_negative_finding(ev):
    source(ev)
    ev.site.page("/down", "<p>busy</p>", status=503)
    app = collect(ev, work_url_1=url(ev, "/down"))
    for _ in range(3):
        PendingAction.objects.filter(kind="fetch_evidence", status="queued").update(due_at=Now())
        run_worker()
    [item] = items(app)
    assert (item.status, item.reason_code) == ("unavailable", "http_503")
    assert len([r for r in ev.site.requests if r["path"] == "/down"]) == 2  # the attempt bound
    assert EvidenceCapture.objects.count() == 0 and Application.objects.get(pk=app.pk).stage == "assessing"


def test_p3_17_captures_are_immutable_and_hold_no_raw_bytes(ev):
    source(ev)
    ev.site.page("/w", "<script>evil()</script><p>Visible <span hidden>hidden text</span>work.</p><!-- comment -->")
    collect(ev, work_url_1=url(ev, "/w"))
    capture = EvidenceCapture.objects.get()
    assert capture.derived_text == "Visible work." and capture.derivation_version == 1 and capture.is_derivative
    assert capture.response_sha256 != capture.derived_sha256 and capture.cannot_prove.startswith("A work page")
    app_role = ev.committed.connect("app", autocommit=True)
    for statement in ("UPDATE assessments_evidencecapture SET derived_text = 'x'", "DELETE FROM assessments_evidencecapture"):
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            app_role.execute(statement)
    owner = ev.committed.connect("owner", autocommit=True)
    with pytest.raises(errors.InsufficientPrivilege):
        owner.execute("UPDATE assessments_evidencecapture SET derived_text = 'x'")  # the trigger binds the owner too
    columns = owner.execute("SELECT column_name, data_type FROM information_schema.columns"
                            " WHERE table_name LIKE 'assessments\\_%'").fetchall()
    assert [c for c in columns if c[1] == "bytea"] == []


def test_p3_19_completion_happens_once_when_the_last_fetches_finish(ev):
    source(ev)
    for n in (1, 2, 3):
        ev.site.page(f"/w{n}", f"<p>Work {n}.</p>")
    app = collect(ev, work_url_1=url(ev, "/w1"), work_url_2=url(ev, "/w2"), work_url_3=url(ev, "/w3"))
    assert app.stage == "assessing"
    assert ApplicationEvent.objects.filter(application=app, kind="evidence_collection_complete").count() == 1
    assert {i.status for i in items(app)} == {"fetched"}
    from assessments.models import AssessmentRun

    assert AssessmentRun.objects.filter(application=app).count() == 1  # step 3 hands over to exactly one run (3C)


def test_p3_20_a_required_unavailable_item_holds_for_staff_until_they_proceed_or_refetch(ev):
    source(ev, required=True)
    ev.site.page("/gone", "<p>x</p>", status=403)
    app = collect(ev, work_url_1=url(ev, "/gone"))
    assert app.stage == "evidence"
    [staff_item] = StaffItem.objects.filter(reason_code="evidence_required_unavailable", status="open")
    with pytest.raises(PermissionDenied):
        services.proceed_without(app.pk, ev.operator)  # a correspondence operator is not an assessment operator
    ev.site.page("/gone", "<p>Back again.</p>")
    [old] = items(app)
    new = services.refetch_item(old.pk, ev.assessor, "synthetic retry")
    assert new.round == 2 and StaffItem.objects.get(pk=staff_item.pk).status == "resolved"
    run_worker()
    app.refresh_from_db()
    assert app.stage == "assessing" and EvidenceItem.objects.get(pk=old.pk).status == "unavailable"


def test_p3_20_proceed_without_moves_on_and_resolves_the_item(ev):
    source(ev, required=True)
    ev.site.page("/gone", "<p>x</p>", status=403)
    app = collect(ev, work_url_1=url(ev, "/gone"))
    services.proceed_without(app.pk, ev.assessor, "staff accept proceeding")
    app.refresh_from_db()
    assert app.stage == "assessing"
    assert StaffItem.objects.get(reason_code="evidence_required_unavailable").status == "resolved"
    assert ApplicationEvent.objects.get(kind="evidence_collection_complete").data["proceeded_without"] is True
    from assessments.models import AssessmentRun

    assert AssessmentRun.objects.filter(application=app).count() == 1  # proceeding hands over to one run (3C)


def test_a_pause_holds_collection_and_no_model_or_assessment_runs(ev):
    source(ev)
    ev.site.page("/w", "<p>Work.</p>")
    app = apply(ev, work_url_1=url(ev, "/w"))
    activate()
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "contact_verified" and ev.site.requests == []
    assert not PendingAction.objects.filter(kind="run_assessment").exists()


# --- sources and staff screens ----------------------------------------------------------------------------

def test_source_approval_needs_the_owner_role_and_the_exact_digest(ev):
    draft = source(ev, approve=False)
    with pytest.raises(PermissionDenied):
        services.approve_evidence_source(draft.pk, ev.assessor, draft.definition_sha256)
    with pytest.raises(services.Refused, match="source_changed_since_shown"):
        services.approve_evidence_source(draft.pk, ev.source_owner, "0" * 64)
    approved = services.approve_evidence_source(draft.pk, ev.source_owner, draft.definition_sha256)
    second = services.define_evidence_source(key=draft.key, kind=draft.kind, host=HOST, port=ev.site.port,
                                             max_bytes=1000, deadline_seconds=5, fixture_only=True)
    services.approve_evidence_source(second.pk, ev.source_owner, second.definition_sha256)
    assert EvidenceSource.objects.get(pk=approved.pk).status == "retired"  # one approved version per key


def test_the_evidence_screen_shows_claims_beside_observations_for_assessment_roles_only(ev):
    source(ev)
    hostile = "<script>x</script>‮"
    ev.site.page("/w", f"<p>Work {hostile}</p>")
    app = collect(ev, work_url_1=url(ev, "/w"), contribution=f"I did it {hostile}", cred_name_1="Unchecked cert",
                  cred_identifier_1="ID-9", no_certifications="")
    page_url = reverse("assessments_staff:evidence", args=[app.public_ref])
    owner_only = staff(ev, "template-owner-p3", "Template owner")
    for user in (owner_only, ev.operator, staff(ev, "root-p3", superuser=True)):
        c = Client()
        c.force_login(user)
        assert c.get(page_url).status_code == 403
    c = Client()
    c.force_login(ev.assessor)
    response = c.get(page_url)
    page = response.content.decode()
    assert response.status_code == 200 and "no-store" in response["Cache-Control"]
    assert "<script>" not in page and "‮" not in page and "[U+202E]" in page
    assert f'href="{url(ev, "/w")}' not in page  # an applicant URL is text, never a link
    assert "No observation (unsupported assertion" in page and "cannot prove who wrote it" in page


def test_no_provider_client_or_network_library_is_imported_by_assessments():
    from pathlib import Path

    from tests import support

    for path in Path(support.ROOT, "assessments").rglob("*.py"):
        text = path.read_text().lower()
        # bgl.12: the live branch (assessments/live.py) alone names the provider and imports its client, behind an
        # activation that is off in code; the fetcher and everything else stay free of any client or network library
        allowed = ("import openai", "from openai", "minimax") if path.name == "live.py" else ()
        for banned in ("import openai", "from openai", "anthropic", "minimax", "import requests", "import httpx", "urllib.request"):
            assert banned in allowed or banned not in text, (path.name, banned)



# --- the scoped security review of 41e2820 ------------------------------------------------------------------

def test_p3_14_the_deadline_bounds_a_server_that_drips_its_headers(ev):
    import time

    src = source(ev, deadline_seconds=1)

    def drip_headers(handler):
        handler.wfile.write(b"HTTP/1.1 200 OK\r\n")
        for _ in range(40):
            time.sleep(0.2)  # each byte arrives well inside any per-receive timeout
            try:
                handler.wfile.write(b"X")
                handler.wfile.flush()
            except OSError:
                return
    ev.site.routes["/slow-headers"] = drip_headers
    started = time.monotonic()
    with pytest.raises(fetch.Transient, match="deadline_exceeded"):
        fetch.fetch(url(ev, "/slow-headers"), src)
    assert time.monotonic() - started < 3  # the total deadline, not one receive at a time
    slow = source(ev, key="slow-body", deadline_seconds=1, content_types=["text/plain"])
    ev.site.routes["/drip-body"] = slow_drip(0.2, 50)
    started = time.monotonic()
    with pytest.raises(fetch.Transient, match="deadline_exceeded"):
        fetch.fetch(url(ev, "/drip-body"), slow)
    assert time.monotonic() - started < 3


@pytest.mark.parametrize("bad", ["https://[x", "https://evidence.example.test/w?q=caf\u00e9\u2603", "https://evidence.example.test:0/w"])
def test_p3_15_a_malformed_applicant_url_is_refused_and_never_leaves_the_application_stuck(ev, bad):
    src = source(ev)
    with pytest.raises(fetch.Refused):
        fetch.validate_url(bad, src, {HOST}) if "q=" not in bad else _send(ev, src, bad)


def _send(ev, src, bad):
    ev.site.page("/w", "<p>ok</p>")
    fetch.fetch(bad.replace("evidence.example.test", f"evidence.example.test:{ev.site.port}"), src)
    raise fetch.Refused("sent")  # a correctly quoted request is acceptable too; it must not raise anything else


def test_p3_15_a_malformed_url_claim_ends_refused_and_collection_completes(ev):
    source(ev)
    app = collect(ev, work_url_1="https://[x")
    [item] = items(app)
    assert item.status == "refused" and app.stage == "assessing"


def test_p3_05_fetch_itself_refuses_a_host_off_the_settings_list_and_fixtures_outside_test(ev, settings):
    src = source(ev)
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = []
    with pytest.raises(fetch.Refused, match="host_not_allowed"):
        fetch.fetch(url(ev, "/w"), src)
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = [HOST]
    settings.CATALYST_ENV = "development"
    with pytest.raises(fetch.Refused, match="fixture_source_outside_test"):
        fetch.fetch(url(ev, "/w"), src)
    assert ev.site.requests == []
    settings.CATALYST_ENV = "staging"  # synthetic: the same fixture source is fetched (6B.1, D-49)
    fetch.fetch(url(ev, "/w"), src)
    assert len(ev.site.requests) == 1
    settings.CATALYST_ENV = "test"


def test_p3_05_the_path_prefix_is_a_path_segment_prefix():
    src = EvidenceSource(host=HOST, port=443, path_prefix="/u/alice")
    assert fetch.validate_url("https://evidence.example.test/u/alice/work", src, {HOST})
    assert fetch.validate_url("https://evidence.example.test/u/alice", src, {HOST})
    for other in ("/u/alice-evil/x", "/u/alices"):
        with pytest.raises(fetch.Refused, match="path_not_allowed"):
            fetch.validate_url(f"https://evidence.example.test{other}", src, {HOST})


def test_a_server_chosen_codec_is_never_used_and_error_pages_are_not_stored(ev):
    result = fetch.FetchResult("u", 200, "text/plain;charset=punycode", "", "caf\u00e9".encode(), False, "1.2.3.4")
    assert fetch.derive(result).text == "caf\u00e9"  # decoded as UTF-8, never through the server's codec
    src = source(ev)
    ev.site.page("/missing", "<p>secret error page</p>", status=404)
    assert fetch.fetch(url(ev, "/missing"), src).body == b""



# --- the QA review of 41e2820: job semantics and source outcomes -------------------------------------------

def _claim(kind="fetch_evidence"):
    from workflow import ledger

    claim = ledger.claim_next({"fetch_evidence": collection.FetchEvidence(),
                               "start_evidence_collection": collection.StartEvidenceCollection()})
    assert claim is not None and claim.kind == kind
    return claim


def _started(ev, *paths):
    source(ev)
    for p in paths:
        ev.site.page(p, f"<p>Work at {p}.</p>")
    app = apply(ev, **{f"work_url_{n}": url(ev, p) for n, p in enumerate(paths, start=1)})
    activate()
    collection.StartEvidenceCollection().run(_claim("start_evidence_collection"))
    return Application.objects.get(pk=app.pk)


def test_p3_lease_loss_discards_the_fetched_result(ev):
    app = _started(ev, "/w")
    claim = _claim()
    owner = ev.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE workflow_pendingaction SET lease_token = gen_random_uuid() WHERE id = %s", [claim.id])
    collection.FetchEvidence().run(claim)  # another claim owns it: nothing is fetched or recorded
    assert EvidenceCapture.objects.count() == 0 and items(app)[0].status == "pending"
    assert all(r["path"] != "/w" for r in ev.site.requests)


def test_p3_a_result_whose_lease_was_lost_during_the_fetch_is_discarded(ev, monkeypatch):
    app = _started(ev, "/w")
    claim = _claim()
    owner = ev.committed.connect("owner", autocommit=True)
    real = collection.fetch.fetch

    def fetch_then_lose_lease(url, source):
        result = real(url, source)
        owner.execute("UPDATE workflow_pendingaction SET lease_token = gen_random_uuid() WHERE id = %s", [claim.id])
        return result
    monkeypatch.setattr(collection.fetch, "fetch", fetch_then_lose_lease)
    collection.FetchEvidence().run(claim)
    assert EvidenceCapture.objects.count() == 0 and items(app)[0].status == "pending"  # the stale result is discarded


def test_p3_a_handler_defect_is_retried_then_recorded_once(ev, monkeypatch):
    app = _started(ev, "/w")
    calls = {"n": 0}
    real = collection.FetchEvidence._record

    def flaky(self, claim, result):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic crash after the fetch")
        return real(self, claim, result)
    monkeypatch.setattr(collection.FetchEvidence, "_record", flaky)
    run_worker()
    assert EvidenceCapture.objects.count() == 1 and items(app)[0].status == "fetched"
    assert Application.objects.get(pk=app.pk).stage == "assessing"


def test_p3_a_job_that_cannot_finish_opens_a_staff_item_and_never_leaves_the_application_stuck(ev, monkeypatch):
    app = _started(ev, "/w")

    def defect(url, source):
        raise RuntimeError("synthetic defect")
    monkeypatch.setattr(collection.fetch, "fetch", defect)
    run_worker()
    [item] = items(app)
    assert (item.status, item.reason_code) == ("unavailable", "handler_error")
    assert StaffItem.objects.filter(reason_code="evidence_collection_failed", status="open").count() == 1
    assert Application.objects.get(pk=app.pk).stage == "assessing"


def test_p3_a_pause_after_the_claim_refunds_the_attempt(ev):
    app = _started(ev, "/w")
    claim = _claim()
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    collection.FetchEvidence().run(claim)
    action = PendingAction.objects.get(pk=claim.id)
    assert (action.status, action.last_error, action.attempts) == ("queued", "automation_paused", 0)
    assert ev.site.requests == [] or all(r["path"] != "/w" for r in ev.site.requests)


def test_p3_19_two_last_fetches_racing_complete_collection_exactly_once(ev):
    app = _started(ev, "/a", "/b")
    first, second = _claim(), _claim()
    errors = []

    def run(claim):
        try:
            collection.FetchEvidence().run(claim)
        except Exception as exc:
            errors.append(repr(exc))
    threads = [ev.committed.thread(run, first), ev.committed.thread(run, second)]
    for t in threads:
        t.join(timeout=30)
    assert errors == [] and {i.status for i in items(app)} == {"fetched"}
    # 9kg.24: each fetch asks the worker for the completion check; the two checks race in turn.
    from workflow import ledger

    handler = collection.CompleteEvidenceCollection()
    checks = [ledger.claim_next({collection.COMPLETE: handler}) for _ in range(2)]
    assert all(c is not None and c.kind == collection.COMPLETE for c in checks)
    threads = [ev.committed.thread(handler.run, c) for c in checks]
    for t in threads:
        t.join(timeout=30)
    assert ApplicationEvent.objects.filter(application=app, kind="evidence_collection_complete").count() == 1
    assert Application.objects.get(pk=app.pk).stage == "assessing"


@pytest.mark.parametrize(("status", "item_status", "outcome"), [(401, "unavailable", None), (403, "unavailable", None),
                                                                (404, "fetched", "not_found"), (410, "fetched", "not_found")])
def test_p3_18_private_and_missing_pages_are_never_negative_findings(ev, status, item_status, outcome):
    source(ev)
    ev.site.page("/p", "<p>secret</p>", status=status)
    app = collect(ev, work_url_1=url(ev, "/p"))
    [item] = items(app)
    assert item.status == item_status and app.stage == "assessing"
    if outcome:
        capture = item.captures.get()
        assert capture.outcome == outcome and capture.derived_text == ""  # an error page is never stored
    assert len([r for r in ev.site.requests if r["path"] == "/p"]) == 1  # not retried


def test_p3_13_redirect_hosts_are_bounded_by_the_settings_list(ev, settings):
    src = source(ev, redirect_hosts=[MIRROR])
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = [HOST]  # MIRROR listed on the source but not in settings
    ev.site.page("/w", "", status=302, Location=url(ev, "/m", host=MIRROR))
    with pytest.raises(fetch.Refused, match="host_not_allowed"):
        fetch.fetch(url(ev, "/w"), src)


def test_the_longest_matching_path_prefix_selects_the_source(ev):
    source(ev, key="broad", path_prefix="/")
    narrow = source(ev, key="narrow", path_prefix="/docs")
    assert collection.approved_source("work_sample_page", url(ev, "/docs/x")) == narrow
    assert collection.approved_source("work_sample_page", url(ev, "/docs-private/x")).key == "broad"



def test_p3_14_the_deadline_bounds_a_server_that_never_finishes_the_tls_handshake(ev, settings):
    import socket as sk
    import threading
    import time

    silent = sk.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(1)
    held = []
    threading.Thread(target=lambda: held.append(silent.accept()), daemon=True).start()  # accepts, never answers
    src = services.define_evidence_source(key="silent", kind="work_sample_page", host=HOST, port=silent.getsockname()[1],
                                          fixture_only=True, max_bytes=1000, deadline_seconds=1)
    src = services.approve_evidence_source(src.pk, ev.source_owner, src.definition_sha256)
    started = time.monotonic()
    with pytest.raises(fetch.Transient, match="deadline_exceeded"):
        fetch.fetch(f"https://{HOST}:{silent.getsockname()[1]}/w", src)
    assert time.monotonic() - started < 3
    silent.close()



def test_hostile_html_is_derived_in_bounded_time():
    import time

    body = ("<a>" * 40_000 + "</z>" * 35_000 + "<p>end</p>").encode()
    started = time.monotonic()
    derived = fetch.derive(fetch.FetchResult("u", 200, "text/html", "", body, False, "1.2.3.4"))
    assert time.monotonic() - started < 5 and derived.truncated
    nested = "<div hidden>" + "<span>" * 100 + "secret" + "</span>" * 100 + "</div><p>shown</p>"
    text = fetch.derive(fetch.FetchResult("u", 200, "text/html", "", nested.encode(), False, "1.2.3.4")).text
    assert "secret" not in text and "shown" in text
