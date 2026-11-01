"""Talent search reads adopted claims only, under existing staff authority; verification stays off."""

from django.test import Client
from django.urls import reverse

from applications.models import Application, SubmissionVersion
from correspondence.talent import profiles
from tests.test_erasure import decided, erase  # noqa: F401
from tests.test_first_generation_import import import_v1, v1  # noqa: F401
from tests.test_evidence import apply
from tests.test_intake import post
from tests.test_intake_fields import ROWS
from tests.test_outbound import p2, staff  # noqa: F401
from workflow.models import PendingAction


def screen(env, user=None, **query):
    client = Client()
    if user is None:
        if not hasattr(env, "talent_reader"):
            env.talent_reader = staff(env, "talent-reader", "Correspondence operator")
        user = env.talent_reader
    client.force_login(user)
    return client.get(reverse("correspondence_staff:talent"), query)


def test_talent_search_matches_confirmed_values_across_fields_and_not_private_data(p2):
    app = apply(
        p2,
        **ROWS,
        contribution="Building reliable robotics systems.",
        experience="Python engineering",
        confidential="on",
        confidential_description="Hiddenprojectsecret under agreement.",
    )
    for query in (
        "synthetic computing",
        "practitioner board",
        "PYTHON robotics",
        "Ada",
    ):
        assert list(profiles(query).values_list("application_id", flat=True)) == [
            app.pk
        ]
    for query in (
        "identifier",
        "no_degree",
        "Hiddenprojectsecret",
        "442079460958",
        "absentword",
    ):
        assert not profiles(query).exists()
    page = screen(p2, q="computing board")
    assert page.status_code == 200 and "no-store" in page["Cache-Control"]
    for text in (
        "BSc Computing",
        "Synthetic Board",
        "SP-0001",
        "self-reported",
        "verification is off",
    ):
        assert text in page.content.decode()
    assert "Hiddenprojectsecret" not in page.content.decode()
    # Searching does not schedule credential verification or any other work.
    before = list(PendingAction.objects.values_list("pk", "status"))
    assert screen(p2, q="robotics").status_code == 200
    assert list(PendingAction.objects.values_list("pk", "status")) == before


def test_talent_unverified_submissions_cannot_create_or_replace_a_profile(p2):
    assert post(Client(), **ROWS).status_code == 302
    assert not profiles().exists()
    app = apply(p2, **ROWS)
    adopted = app.adoptions.get().submission_version_id
    assert (
        post(Client(), **{**ROWS, "cred_name_1": "Unconfirmedexpert"}).status_code
        == 302
    )
    assert SubmissionVersion.objects.filter(application=app).count() == 3
    assert not profiles("Unconfirmedexpert").exists()
    assert profiles("practitioner").get().submission_version_id == adopted


def test_talent_pages_require_staff_permission_and_escape_claims(p2):
    hostile = "<script>Institute</script>\u202eevil"
    apply(p2, **{**ROWS, "edu_institution_1": hostile})
    url = reverse("correspondence_staff:talent")
    assert Client().get(url).status_code == 302
    for user in (
        staff(p2, "nobody"),
        staff(p2, "root", superuser=True),
        staff(p2, "templates-only", "Template owner"),
    ):
        assert screen(p2, user).status_code == 403
    page = screen(p2)
    text = page.content.decode()
    assert page.status_code == 200 and "&lt;script&gt;Institute" in text
    assert "<script>" not in text and "\u202e" not in text and "[U+202E]" in text
    client = Client()
    client.force_login(staff(p2, "post-user", "Correspondence operator"))
    assert client.post(url, {"q": "Institute"}).status_code == 405


def test_talent_search_paginates_and_validates_queries_without_losing_results(
    p2, monkeypatch
):
    monkeypatch.setattr("correspondence.talent.PAGE_SIZE", 1)
    older = apply(p2, **ROWS)
    newer = apply(p2, **ROWS, email="second@example.test", name="Second Example")
    page = screen(p2, q="synthetic", page=1)
    assert page.context["page"].paginator.count == 2
    assert [row.application_id for row in page.context["page"]] == [newer.pk]
    assert b"q=synthetic&amp;page=2" in page.content
    page = screen(p2, q="synthetic", page=2)
    assert [row.application_id for row in page.context["page"]] == [older.pk]
    assert b"No confirmed profiles match" in screen(p2, q="missingterm").content
    for query in ({"q": "x" * 201}, {"page": "invalid"}, {"page": "0"}):
        assert screen(p2, **query).status_code == 400
    assert screen(p2, q="' & ! | (").status_code == 200


def test_talent_erasure_removes_profile_and_search_matches(p2, decided):
    app = apply(p2, **ROWS)
    assert profiles("computing").exists()
    PendingAction.objects.filter(subject_id=app.public_ref).update(
        status=PendingAction.Status.CANCELLED
    )
    Application.objects.filter(pk=app.pk).update(stage="withdrawn")
    assert erase(p2.committed, app.public_ref).status == "erased"
    assert not profiles().exists() and not profiles("computing").exists()
    assert b"Synthetic Institute" not in screen(p2).content


def test_talent_search_keeps_imported_credentials_without_activating_verification(v1):
    v1.case(
        "active", "Legacy Example", "legacy@example.test", reference="CAT-AC00-0011"
    )
    v1.case(
        "requested",
        "Unverified Example",
        "unverified@example.test",
        reference="CAT-RQ00-0001",
        verified=False,
    )
    _, report = import_v1(v1)
    assert report["failures"] == []
    for query in ("university studies", "cert issuer", "Legacy"):
        assert list(
            profiles(query).values_list("application__reference", flat=True)
        ) == ["CAT-AC00-0011"]
    assert not profiles("Unverified").exists()
    assert not PendingAction.objects.exists()
