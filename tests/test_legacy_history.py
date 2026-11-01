"""Legacy handover context is available to dossier readers, without replaying any operation."""

import uuid
from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import reverse

from firstgen.models import ImportedCase, ImportedRecord
from firstgen.staff_views import GUIDANCE, displayed_fields
from tests.firstgen_v1 import new_id
from tests.test_first_generation_import import STAGES, import_v1, populate, v1  # noqa: F401 (fixture)
from tests.test_staff import change_url, logged_in, make_user
from workflow.models import AutomationPause, PendingAction


def history(case):
    return reverse("firstgen_staff:history", args=[case.application.public_ref])


def test_legacy_history_is_available_for_every_imported_state_without_changing_cases(v1, privileged_reset):
    populate(v1)
    import_v1(v1)
    client = logged_in(make_user(privileged_reset, "legacy-reader"))
    pauses = list(AutomationPause.objects.order_by("pk").values())
    assert PendingAction.objects.count() == 0
    assert set(state for state, _ in STAGES.values()) == set(GUIDANCE)
    for case in ImportedCase.objects.select_related("application"):
        response = client.get(history(case))
        assert response.status_code == 200
        shown = response.content.decode()
        assert case.reference in shown and GUIDANCE[case.v1_state] in shown
        assert "does not prove the current provider state" in shown
        assert "no-store" in response["Cache-Control"]
        assert history(case) in client.get(change_url(case.application)).content.decode()
    case = ImportedCase.objects.get(reference="CAT-NI00-0004")
    shown = client.get(history(case)).content.decode()
    assert "Hello, which part did you build?" in shown and "I built the planner." in shown
    assert PendingAction.objects.count() == 0
    assert list(AutomationPause.objects.order_by("pk").values()) == pauses


def test_legacy_history_requires_the_dossier_permission_and_refuses_writes(v1, privileged_reset):
    populate(v1)
    import_v1(v1)
    case = ImportedCase.objects.first()
    url = history(case)
    anonymous = Client().get(url)
    assert anonymous.status_code == 302 and case.reference not in anonymous.content.decode()
    forbidden = logged_in(make_user(privileged_reset, "legacy-no-grant", group=False)).get(url)
    assert forbidden.status_code == 403 and case.reference not in forbidden.content.decode()
    client = logged_in(make_user(privileged_reset, "legacy-readonly"))
    before = list(ImportedCase.objects.order_by("pk").values())
    for method in (client.post, client.put, client.delete):
        assert method(url).status_code == 405
    assert before == list(ImportedCase.objects.order_by("pk").values())
    assert client.get(reverse("firstgen_staff:history", args=[uuid.uuid4()])).status_code == 404
    assert client.get(url, {"table": "unknown_source_table"}).status_code == 404


def test_legacy_history_escapes_source_text_and_does_not_display_unreviewed_fields(v1, privileged_reset):
    ids = populate(v1)
    hostile = ("<script>synthetic()</script>\u202e "
               "https://example.test/%63onfirm/synthetic-confirm-secret/ "
               "https://example.test/setup/synthetic-setup-secret/ "
               "https://example.test/sign/synthetic-signing-secret")
    v1.insert("applicant_message", id=new_id(), case_id=ids["CAT-NI00-0004"], direction="in",
              sent_at=v1.at(35), subject="Synthetic hostile subject", body_text=hostile,
              source_key="synthetic-hidden-source-key", created_at=v1.at(35))
    import_v1(v1)
    client = logged_in(make_user(privileged_reset, "legacy-escaped"))
    case = ImportedCase.objects.get(reference="CAT-NI00-0004")
    shown = client.get(history(case), {"table": "applicant_message"}).content.decode()
    assert "&lt;script&gt;synthetic()&lt;/script&gt;[U+202E]" in shown
    assert hostile not in shown and "synthetic-hidden-source-key" not in shown
    assert all(secret not in shown for secret in ("synthetic-confirm-secret", "synthetic-setup-secret", "synthetic-signing-secret"))
    unknown = SimpleNamespace(v1_table="review_run", data={"output": "unreviewed model text"})
    assert displayed_fields(unknown) == []
    assert displayed_fields(SimpleNamespace(v1_table="applicant_message", data={"body_text": {"secret": "hidden"}})) == []
    assert displayed_fields(SimpleNamespace(v1_table="applicant_message", data={"_erased": True})) == []
    assert displayed_fields(SimpleNamespace(v1_table="applicant_message", data={
        "direction": "out", "template": "unknown_welcome", "body_text": "synthetic credential"})) == [("direction", "out")]


def test_legacy_history_paginates_all_records_with_case_and_table_scope(v1, privileged_reset):
    ids = populate(v1)
    for n in range(55):
        v1.event(ids["CAT-NI00-0004"], "needs_information", "needs_information", "synthetic_history", 100 + n)
    import_v1(v1)
    client = logged_in(make_user(privileged_reset, "legacy-pages"))
    case = ImportedCase.objects.get(reference="CAT-NI00-0004")
    expected = set(ImportedRecord.objects.filter(application=case.application, v1_table="case_event").values_list("pk", flat=True))
    found = []
    for number in (1, 2):
        response = client.get(history(case), {"table": "case_event", "page": number})
        assert response.status_code == 200
        assert response.context["page"].paginator.count == len(expected)
        rows = response.context["rows"]
        assert all(record.application_id == case.application_id and record.v1_table == "case_event" for record, _ in rows)
        found.extend(record.pk for record, _ in rows)
    assert set(found) == expected and len(found) == len(expected)


def test_legacy_import_pause_requires_decision_maker_review_and_a_recorded_reason(v1, privileged_reset):
    from correspondence import staff_actions
    from correspondence.common import Refused
    from correspondence.roles import DECISION_MAKER, OPERATOR
    from tests.test_outbound import staff

    populate(v1)
    import_v1(v1)
    case = ImportedCase.objects.get(reference="CAT-AC00-0011")
    pause = AutomationPause.objects.get(subject_id=case.application.public_ref)
    assert pause.actor_ref == "system:import:first-generation" and staff_actions.is_system_pause(pause)
    assert staff_actions.is_system_pause(SimpleNamespace(actor_ref="import:first-generation"))
    env = SimpleNamespace(committed=privileged_reset)
    operator = staff(env, "legacy-operator", OPERATOR)
    decider = staff(env, "legacy-decider", DECISION_MAKER)
    with pytest.raises(Refused, match="decision_maker_review_required"):
        staff_actions.resume(case.application_id, operator, "The imported case looks ready")
    with pytest.raises(Refused, match="reason_needed"):
        staff_actions.resume(case.application_id, decider, "ok")
    assert AutomationPause.objects.filter(pk=pause.pk).exists()
    staff_actions.resume(case.application_id, decider, "Reviewed existing mailbox and account ownership")
    assert not AutomationPause.objects.filter(pk=pause.pk).exists()
    event = case.application.events.get(kind="automation_resumed")
    assert event.actor_ref == f"user:{decider.pk}" and event.data["system_pause"] is True
    assert PendingAction.objects.count() == 0  # resumption records review; it does not invent missing continuation jobs


def test_contact_confirmation_preserves_imported_progress_and_does_not_restart_onboarding(v1, privileged_reset):
    from django.core.exceptions import PermissionDenied
    from psycopg import sql

    from applications import confirmation
    from applications.models import VersionAdoption
    from correspondence import processing, staff_actions
    from correspondence.models import StaffItem
    from correspondence.roles import DECISION_MAKER, OPERATOR
    from tests.test_confirmation import active_challenge, link_for, post_confirm, snapshot
    from tests.test_outbound import staff

    populate(v1)
    # v1 could progress without email verification. Exercise the real importer with that source state.
    v1.owner.execute(sql.SQL("UPDATE {}.intake_request SET email_verified_at = NULL, email_verified_via = NULL")
                     .format(sql.Identifier(v1.schema)))
    import_v1(v1)
    operator = staff(SimpleNamespace(committed=privileged_reset), "legacy-verification", OPERATOR)
    decider = staff(SimpleNamespace(committed=privileged_reset), "legacy-confirmation-review", DECISION_MAKER)
    cases = ImportedCase.objects.select_related("application").filter(
        application__stage__in=("assessing", "awaiting_answers", "awaiting_decision", "agreements",
                               "agreements_complete", "provisioning", "active"))
    tested = set()
    for case in cases:
        app = case.application
        tested.add(app.stage)
        before_stage = app.stage
        before_pause = list(AutomationPause.objects.filter(subject_id=app.public_ref).values())
        before_records = list(ImportedRecord.objects.filter(application=app).order_by("pk").values())
        staff_actions.resend_verification(app.pk, operator, "Verify contact for handover review", expected_number=1)
        challenge = active_challenge(app)
        version = app.versions.order_by("-version_number").first()
        link = link_for(app)
        response = post_confirm(Client(), link, version.public_id)
        assert response.status_code == 200 and "Email address confirmed" in response.content.decode()
        app.refresh_from_db()
        assert app.stage == before_stage and app.contact_verified_at is not None
        assert list(AutomationPause.objects.filter(subject_id=app.public_ref).values()) == before_pause
        assert list(ImportedRecord.objects.filter(application=app).order_by("pk").values()) == before_records
        assert VersionAdoption.objects.get(application=app).submission_version_id == version.pk
        assert StaffItem.objects.filter(application=app, reason_code="contact_verified_existing_workflow",
                                        status="open").count() == 1
        assert list(PendingAction.objects.filter(subject_id=app.public_ref).values_list("kind", flat=True)) == [
            "send_verification"]
        before_replay = snapshot()
        with pytest.raises(confirmation.Refused, match="already confirmed"):
            confirmation.confirm(challenge.public_id, version.public_id)
        assert snapshot() == before_replay
        item = StaffItem.objects.get(application=app, reason_code="contact_verified_existing_workflow")
        with pytest.raises(PermissionDenied):
            processing.resolve_exception(item.pk, "acknowledge", operator)
        processing.resolve_exception(item.pk, "acknowledge", decider, "Reviewed the recorded contact confirmation")
        item.refresh_from_db()
        assert item.status == "resolved"
        assert list(AutomationPause.objects.filter(subject_id=app.public_ref).values()) == before_pause
        assert PendingAction.objects.filter(subject_id=app.public_ref).count() == 1
    assert tested == {"assessing", "awaiting_answers", "awaiting_decision", "agreements",
                      "agreements_complete", "provisioning", "active"}
