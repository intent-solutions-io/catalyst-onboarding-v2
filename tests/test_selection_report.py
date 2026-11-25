"""Selection reporting uses existing counts without exposing dossiers or gaining authority."""

from types import SimpleNamespace

from django.contrib.messages.storage.base import Message
from django.contrib.messages.storage.cookie import CookieStorage
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
import pytest

from assessments import agent, scorecard
from assessments.scorecard_views import ROW_LABELS
from tests.test_assessment import a  # noqa: F401
from tests.test_clarification import c  # noqa: F401
from tests.test_decision import d, decide, ready_app  # noqa: F401
from tests.test_evidence import ev  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2, staff  # noqa: F401


def qualified_user(committed, name="report-reviewer", **kwargs):
    user = staff(SimpleNamespace(committed=committed), name, **kwargs)
    committed.connect("owner", autocommit=True).execute(
        "INSERT INTO accounts_user_user_permissions (user_id, permission_id) "
        "SELECT %s, id FROM auth_permission WHERE codename = 'record_qualification_decision'",
        [user.pk],
    )
    return user


@pytest.mark.parametrize("role", ["anonymous", "ungranted", "superuser", "nonstaff"])
def test_selection_report_refuses_other_roles_before_queries(
    privileged_reset, monkeypatch, role
):
    def refuse():
        pytest.fail("unauthorized request reached reporting queries")

    monkeypatch.setattr(scorecard, "scorecard", refuse)
    client = Client()
    if role != "anonymous":
        if role == "ungranted":
            user = staff(SimpleNamespace(committed=privileged_reset), role)
        else:
            user = qualified_user(privileged_reset, role, superuser=role == "superuser")
        if role == "nonstaff":
            privileged_reset.connect("owner", autocommit=True).execute(
                "UPDATE accounts_user SET is_staff = false WHERE id = %s", [user.pk]
            )
            user.refresh_from_db()
        client.force_login(user)
    response = client.get(reverse("assessments_staff:selection_report"))
    assert response.status_code == (302 if role == "anonymous" else 403)
    assert "Recorded evidence" not in response.content.decode()


def test_selection_report_preserves_zero_unknowns_and_rejects_writes(privileged_reset):
    client = Client()
    client.force_login(qualified_user(privileged_reset))
    notices = CookieStorage(None)
    client.cookies[notices.cookie_name] = notices._encode(
        [Message(20, "Private case notice from another staff screen")]
    )
    url = reverse("assessments_staff:selection_report")
    response = client.get(url)
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    rows = response.context["rows"]
    assert [row["label"] for row in rows] == list(ROW_LABELS)
    assert len(rows) == 15
    assert rows[0]["known"] and ("Decided cases", "0") in rows[0]["records"][0]
    assert not rows[2]["known"] and rows[2]["reason"]
    page = response.content.decode()
    assert "Private case notice" not in page
    assert "<title>Selection quality and owner report</title>" in page
    assert "Not measured." in page and "<bdi>0</bdi>" in page
    assert "does not measure the wait of undecided cases" in page
    assert "Changes since the previous review have not been compared" in page
    assert "No rate threshold is applied" in page
    assert client.post(url, {"outcome": "advance"}).status_code == 405
    index = client.get(reverse("admin:index"))
    assert url in index.content.decode()


def test_selection_report_escapes_version_labels(privileged_reset, monkeypatch):
    card = scorecard.scorecard()
    card["rows"]["version_differences"]["value"] = [
        {
            "policy_ref": '<script>alert("policy")</script>\u202e',
            "prompt_pack": "sample",
            "rubric_version": "sample",
            "outcome": "hold",
            "count": 1,
        }
    ]
    monkeypatch.setattr(scorecard, "scorecard", lambda: card)
    client = Client()
    client.force_login(qualified_user(privileged_reset))
    page = client.get(reverse("assessments_staff:selection_report")).content.decode()
    assert "<script>" not in page and "\u202e" not in page
    assert "&lt;script&gt;" in page and "[U+202E]" in page


@pytest.mark.worker_setup
def test_selection_report_matches_existing_queries_without_identifiers_or_effects(
    d, monkeypatch
):
    app = ready_app(d, monkeypatch)
    decide(d, app, "hold")
    expected = scorecard.scorecard()

    def refuse(*args, **kwargs):
        pytest.fail("report attempted model work")

    monkeypatch.setattr(agent, "build_model", refuse)
    monkeypatch.setattr(agent, "run_checked", refuse)
    client = Client()
    client.force_login(d.decider)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("assessments_staff:selection_report"))
    assert response.status_code == 200
    assert response.context["card"] == expected
    assert expected["decisions"] == 1
    # Normal authenticated requests may refresh Django's session. No business record,
    # decision or job may be written by reporting.
    unexpected = [
        query["sql"].lstrip().upper()
        for query in queries
        if not query["sql"]
        .lstrip()
        .upper()
        .startswith(("SELECT", 'UPDATE "DJANGO_SESSION" SET'))
        and query["sql"].strip().upper() not in ("BEGIN", "COMMIT")
    ]
    assert not unexpected, [query.split()[0] for query in unexpected]
    page = response.content.decode()
    for private in (
        app.display_name,
        app.email,
        str(app.public_ref),
        "Read the work sample.",
    ):
        assert private and private not in page
