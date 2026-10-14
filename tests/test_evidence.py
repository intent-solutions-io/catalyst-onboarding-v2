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
from tests.test_outbound import p2, run_worker, staff  # noqa: F401
from workflow.models import AutomationPause, PendingAction

HOST, MIRROR, ELSEWHERE = "evidence.example.test", "mirror.example.test", "elsewhere.example.test"
FORM = reverse("applications:request_access")
BASE = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}


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
            "contribution": "I wrote the parser.", "cred_name_1": "Synthetic cert", "cred_identifier_1": "ID-1"}
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
    assert set(Application.objects.get().versions.get().submitted_fields) == {"name", "email", "reason"}


# --- TEST-P3-09, 10: activation and slots ----------------------------------------------------------------

def test_p3_09_activation_releases_only_eligible_held_rows_with_events(ev):
    source(ev)
    ev.site.page("/w", "<p>A synthetic work page.</p>")
    claimed = apply(ev, work_url_1=url(ev, "/w"))
    bare = apply(ev, email="bob@example.test")  # no claims: an S1-shaped version
    paused = apply(ev, email="cy@example.test", work_url_1=url(ev, "/w"))
    AutomationPause.objects.create(subject_type="application", subject_id=paused.public_ref, reason="synthetic", actor_ref="t")
    with pytest.raises(Exception):
        call_command("activate_evidence_collection", activation_version=2, approval_ref="D-34")
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
                  cred_name_1="Cert", cred_identifier_1="ID-7", cred_url_1=url(ev, "/c"))
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


def test_p3_12_mixed_dns_answers_refuse_and_a_peer_mismatch_sends_nothing(ev, monkeypatch):
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
    for n in range(5):
        ev.site.page(f"/l{n}", "", status=302, Location=url(ev, f"/l{n + 1}"))
    with pytest.raises(fetch.Refused, match="too_many_redirects"):
        fetch.fetch(url(ev, "/l0"), src)


def test_p3_14_the_byte_cap_truncates_and_the_deadline_stops_a_slow_drip(ev):
    src = source(ev, max_bytes=100)
    ev.site.page("/big", "<p>" + "a" * 5000 + "</p>")
    result = fetch.fetch(url(ev, "/big"), src)
    assert result.truncated and len(result.body) == 100
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
    app = collect(ev, work_url_1=url(ev, "/w"))
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
    assert app.stage == "assessing" and EvidenceItem.objects.get(pk=old.pk).status == "refused"


def test_p3_20_proceed_without_moves_on_and_resolves_the_item(ev):
    source(ev, required=True)
    ev.site.page("/gone", "<p>x</p>", status=403)
    app = collect(ev, work_url_1=url(ev, "/gone"))
    services.proceed_without(app.pk, ev.assessor, "staff accept proceeding")
    app.refresh_from_db()
    assert app.stage == "assessing"
    assert StaffItem.objects.get(reason_code="evidence_required_unavailable").status == "resolved"
    assert ApplicationEvent.objects.get(kind="evidence_collection_complete").data["proceeded_without"] is True


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
    app = collect(ev, work_url_1=url(ev, "/w"), contribution=f"I did it {hostile}", cred_name_1="Unchecked cert")
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


def test_no_model_client_or_network_library_is_imported_by_assessments():
    from pathlib import Path

    from tests import support

    for path in Path(support.ROOT, "assessments").rglob("*.py"):
        text = path.read_text().lower()
        for banned in ("pydantic_ai", "openai", "anthropic", "minimax", "import requests", "import httpx", "urllib.request"):
            assert banned not in text, (path.name, banned)
