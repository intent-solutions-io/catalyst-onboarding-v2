"""9kg.50 (029 section 5.2): two states that needed a shell get a supported staff path.

- An application on hold comes back to a decision through the decision service and the decision form (admit or
  decline, never a second hold), with the permission checked and the transition recorded; a user without the
  permission is refused.
- Staff resend the verification message from the correspondence screen under the staff-send permission: the old
  challenge is superseded, the same message goes out through the same handler, a resend is refused beyond the limit,
  and the applicant-facing responses (the message and the confirmation pages) are unchanged.
"""

import re
from urllib.parse import urlencode

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

from applications.models import Application, ContactChallenge
from assessments import decisions
from assessments.models import QualificationDecision
from assessments.services import Refused
from correspondence import staff_actions
from correspondence.common import Refused as CorrespondenceRefused
from correspondence.models import OutboundMessage
from tests.test_assessment import a  # noqa: F401  (fixture chain)
from tests.test_clarification import c  # noqa: F401
from tests.test_decision import d, decide, rationale, ready_app  # noqa: F401
from tests.test_evidence import ev  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import FORM, VALID, p2, run_worker, staff  # noqa: F401
from workflow.models import PendingAction

LINK = re.compile(r"http://catalyst\.example\.test(/confirm/\S+/)")


# --- the hold exit ----------------------------------------------------------------------------------------------

def test_an_on_hold_case_comes_back_to_a_decision_through_the_service(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    decide(d, app, "hold")
    app.refresh_from_db()
    assert app.stage == "on_hold"
    with pytest.raises(Refused, match="already_on_hold"):
        decide(d, app, "hold")  # the way off a hold is a decision, never a second hold
    with pytest.raises(PermissionDenied):  # the same authority rule as any decision
        decide(d, app, "admit", user=staff(d, "operator-hold", "Assessment operator"))
    decision = decide(d, app, "admit")
    app.refresh_from_db()
    assert (app.stage, decision.outcome, decision.basis) == ("admitted", "admit", "model_assisted")
    event = app.events.get(kind="qualification_admit")
    assert event.data["from"] == "on_hold" and event.actor_ref == f"user:{d.decider.pk}" and event.actor_type == "staff"
    assert QualificationDecision.objects.filter(application=app).count() == 2  # the hold stays as history
    assert PendingAction.objects.filter(kind="issue_nda", subject_id=app.public_ref, status="held").exists()


def test_an_on_hold_case_comes_back_through_the_decision_form_and_a_refused_user_sees_403(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    decide(d, app, "hold")
    url = reverse("assessments_staff:decision", args=[app.public_ref])
    client = Client()
    client.force_login(d.decider)
    page = client.get(url).content.decode()
    assert 'value="decline"' in page and 'value="admit"' in page and 'value="hold"' not in page
    assert "not at a stage where a decision can be recorded" not in page
    form = {"digest": decisions.decision_state(app)["digest"], "outcome": "decline", "reason_code": "synthetic_reason"}
    for criterion in rationale():
        form.update({f"cap-{criterion}": "not_shown", f"str-{criterion}": "weak", f"note-{criterion}": "Thin evidence."})
    viewer = staff(d, "viewer-hold", "Assessment operator")
    client.force_login(viewer)
    assert client.post(reverse("assessments_staff:decide", args=[app.public_ref]), form).status_code == 403
    assert Application.objects.get(pk=app.pk).stage == "on_hold"
    client.force_login(d.decider)
    assert client.post(reverse("assessments_staff:decide", args=[app.public_ref]), form).status_code == 302
    assert Application.objects.get(pk=app.pk).stage == "declined"
    assert app.events.filter(kind="qualification_decline", data__from="on_hold").exists()


def test_a_human_only_hold_can_also_leave_through_the_form(d, monkeypatch, settings):
    from tests.test_assessment import valid
    from tests.test_clarification import assessed_with

    bad = valid(quote="A quote that appears nowhere in the evidence")
    app, _ = assessed_with(d, monkeypatch, bad, bad)  # the run failed: human-only from `assessing`
    decide(d, app, "hold", human_only_reason="Read everything myself; waiting for a second sample.")
    app.refresh_from_db()
    assert app.stage == "on_hold" and decisions.decision_state(app)["human_only_allowed"]
    decision = decide(d, app, "decline", human_only_reason="Nothing further arrived; declined on the record.")
    assert decision.basis == "human_only" and Application.objects.get(pk=app.pk).stage == "declined"


# --- the verification resend -------------------------------------------------------------------------------------

def submit(email="ada@example.test"):
    assert Client().post(FORM, urlencode({**VALID, "email": email}), content_type="application/x-www-form-urlencoded").status_code == 302
    return Application.objects.get(email_key=email)


def challenges(app):
    return list(ContactChallenge.objects.filter(application=app).order_by("id"))


def test_staff_resend_supersedes_the_challenge_and_sends_the_same_message(p2):
    app = submit()
    run_worker()
    first_link = LINK.search(mail.outbox[-1].body).group(1)
    first = mail.outbox[-1]
    operator = staff(p2, "resender", "Correspondence operator")
    client = Client()
    client.force_login(operator)
    url = reverse("correspondence_staff:resend_verification", args=[app.public_ref])
    page = client.get(reverse("correspondence_staff:application", args=[app.public_ref])).content.decode()
    assert "Resend the verification message" in page and "0 of 3 staff resend(s) used" in page
    assert client.post(url, {"note": "link reported broken"}).status_code == 302
    old, new = challenges(app)
    assert old.superseded_at is not None and new.superseded_at is None and new.used_at is None
    assert PendingAction.objects.filter(kind="send_verification", input_ref=str(new.public_id), status="queued").exists()
    run_worker()
    second = mail.outbox[-1]
    assert (second.subject, second.to) == (first.subject, first.to) and second.body != first.body  # a new link only
    assert OutboundMessage.objects.filter(application=app).values_list("template_key", "template_version").distinct().count() == 1
    event = app.events.get(kind="verification_resent")
    assert event.data == {"resend_number": 1, "note": "link reported broken"} and event.actor_ref == f"user:{operator.pk}"
    assert str(new.public_id) not in str(event.data) and str(old.public_id) not in str(event.data)
    # The applicant-facing responses are unchanged: the old link is refused as no longer valid, the new one works.
    assert Client().get(first_link).status_code == 410
    new_link = LINK.search(second.body).group(1)
    confirm = Client().get(new_link)
    assert confirm.status_code == 200 and 'name="version"' in confirm.content.decode()


def test_a_resend_is_refused_beyond_the_limit_after_verification_and_without_the_permission(p2, settings):
    settings.CATALYST_VERIFICATION_RESEND_LIMIT = 2
    app = submit()
    operator = staff(p2, "resender-limit", "Correspondence operator")
    assert staff_actions.resend_verification(app.pk, operator) == 1
    assert staff_actions.resend_verification(app.pk, operator) == 2
    with pytest.raises(CorrespondenceRefused, match="resend_limit_reached"):
        staff_actions.resend_verification(app.pk, operator)
    assert len(challenges(app)) == 3 and app.events.filter(kind="verification_resent").count() == 2
    client = Client()
    client.force_login(operator)
    url = reverse("correspondence_staff:resend_verification", args=[app.public_ref])
    assert client.post(url).status_code == 302  # refused with its code on the screen, never a crash
    page = client.get(reverse("correspondence_staff:application", args=[app.public_ref])).content.decode()
    assert "Refused: resend_limit_reached" in page and "Resend the verification message" not in page
    # Without the staff-send permission: a holder of another correspondence permission reaches the page but not the act.
    holder = staff(p2, "pause-only")
    owner = p2.committed.connect("owner", autocommit=True)
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission"
                  " WHERE codename = 'pause_automation'", [holder.pk])
    other = Client()
    other.force_login(type(holder).objects.get(pk=holder.pk))
    assert other.post(url).status_code == 403
    with pytest.raises(PermissionDenied):
        staff_actions.resend_verification(app.pk, staff(p2, "root-resend", superuser=True))
    # Once contact is verified there is nothing to resend.
    run_worker()
    link = LINK.search(mail.outbox[-1].body).group(1)
    version = re.search(r'name="version" value="([^"]+)"', Client().get(link).content.decode()).group(1)
    assert Client().post(link, {"version": version}).status_code == 200
    with pytest.raises(CorrespondenceRefused, match="contact_already_verified"):
        staff_actions.resend_verification(app.pk, operator)
    assert len(challenges(app)) == 3


def test_a_resend_is_refused_while_a_hard_bounce_is_open(p2):
    from django.db import transaction

    from correspondence.staff_items import open_item

    app = submit()
    with transaction.atomic():
        open_item("hard_bounce", f"bounce:{app.public_ref}", application=app)
    with pytest.raises(CorrespondenceRefused, match="hard_bounce_open"):
        staff_actions.resend_verification(app.pk, staff(p2, "resender-bounce", "Correspondence operator"))
    assert len(challenges(app)) == 1


def test_the_dossier_flags_a_case_awaiting_decision_or_on_hold_and_links_the_decision_screen(d, monkeypatch):
    from applications import staff as dossier

    app = ready_app(d, monkeypatch)
    last = dossier.next_steps(app)[-1]
    assert (last.party, last.attention) == ("Staff", True) and "decision screen" in last.text
    assert Application.objects.filter(pk=app.pk).filter(dossier.attention_q()).exists()
    decide(d, app, "hold")
    last = dossier.next_steps(Application.objects.get(pk=app.pk))[-1]
    assert (last.party, last.attention) == ("Staff", True) and "On hold" in last.text and "decision screen" in last.text
    assert Application.objects.filter(pk=app.pk).filter(dossier.attention_q()).exists()
    change = reverse("admin:applications_application_change", args=[app.pk])
    client = Client()
    client.force_login(staff(d, "dossier-decider", "Read-only staff", "Assessment operator"))
    assert "Decision screen" in client.get(change).content.decode()  # review_evidence opens the decision screen
    client.force_login(staff(d, "dossier-reader", "Read-only staff"))
    assert "Decision screen" not in client.get(change).content.decode()
