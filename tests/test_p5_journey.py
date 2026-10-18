"""P5 task 5C: the GATE-P5 journey over real Django HTTP (023 section 9, TEST-P5-24), plus the two cases that need the
P2 inbound path: a bounced welcome (TEST-P5-04) and an emailed "withdraw" (TEST-P5-21).

The journey covers intake, agreements, release, approval, an unknown create that is reconciled and confirmed,
verification, the applicant setting their own password, activation and the welcome, then a withdrawal through the
emailed link and the revocation it triggers. Staff log in through the admin login form, and every staff and applicant
POST carries the page's CSRF token through a client that enforces CSRF. The mail host is the synthetic fake; nothing
is live.
"""

import re

import pytest
from django.core import mail
from django.test import Client
from django.db.models.functions import Now
from django.urls import reverse

from applications.models import Application
from correspondence import inbound
from correspondence.models import ApprovedMessage, InboundMessage, StaffItem
from provisioning.models import AccessRevocation, ProvisioningRequest, WithdrawalConfirmation
from tests.imap_server import ScriptedIMAP
from tests.mxroute_fake import FakeMailHost
from tests.test_closure import WITHDRAW_LINK, active_member, cl  # noqa: F401  (fixture chain and helper)
from tests.test_credentials import LINK, welcome_template
from tests.test_inbound import TRUSTED, collect, reply
from tests.test_p4_journey import csrf, logged_in, sign_over_http
from tests.test_processing import bounce, processed
from tests.test_outbound import staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, complete, d, ev, g, grant, h, k, nda, of, p2, pv, release, request_of,
    run_worker, tls,
)
from tests.test_provisioning import approved as approved_request
from workflow.models import PendingAction

CHOSEN = "applicant-chosen-synthetic-9"  # gitleaks:allow (synthetic; never a real password)
ADDRESS = "ada.example@team.example.test"


def screen(app):
    return reverse("provisioning_staff:provisioning", args=[app.public_ref])


def staff_post(client, app, form):
    """POST from the page the person is looking at, with its CSRF token (nothing else is ever sent)."""
    page = client.get(screen(app)).content.decode()
    return client.post(reverse("provisioning_staff:act", args=[app.public_ref]),
                       {**form, "csrfmiddlewaretoken": csrf(page)})


def applicant_post(path, form):
    browser = Client(enforce_csrf_checks=True)
    page = browser.get(path)
    assert page.status_code == 200
    assert browser.post(path, form).status_code == 403  # no CSRF token: refused
    return browser.post(path, {**form, "csrfmiddlewaretoken": csrf(page.content.decode())})


# --- TEST-P5-24: the journey ------------------------------------------------------------------------------------

def test_p5_24_the_journey_from_intake_to_activation_and_from_withdrawal_to_revocation_over_http(cl, monkeypatch):
    welcome_template(cl)
    app = admitted(cl, monkeypatch)  # intake and confirmation over HTTP, P3 assessment and the admit decision
    approve(cl)
    activate()
    run_worker()
    sign_over_http(cl, app, "nda")
    sign_over_http(cl, app, "user_agreement")
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"
    assert release()["released"] == 1  # the owner's versioned activation of provisioning (TEST-P5-01)
    request = request_of(app)

    approver = logged_in(cl.approver.username)
    page = approver.get(screen(app)).content.decode()
    assert "awaiting the approver" in page and "(owner: approver)" in page and ADDRESS in page
    response = approver.post(reverse("provisioning_staff:act", args=[app.public_ref]),
                             {"action": "approve", "request": str(request.public_id), "digest": request.approval_digest})
    assert response.status_code == 403  # no CSRF token
    assert staff_post(approver, app, {"action": "approve", "request": str(request.public_id),
                                      "digest": request.approval_digest}).status_code == 302

    # Recovery inside the journey: the create's outcome is unknown; a read finds the mailbox, and staff confirm it.
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    request.refresh_from_db()
    assert request.status == "found_by_evidence"
    operator = logged_in(cl.op1.username)
    assert "Record the decision" in operator.get(screen(app)).content.decode()
    assert staff_post(operator, app, {"action": "confirm_found", "request": str(request.public_id),
                                      "decision": "ours", "note": "Limits and timing match our request"}
                      ).status_code == 302
    run_worker()  # verification, then the invitation
    request.refresh_from_db()
    assert request.status == "setup_pending" and Application.objects.get(pk=app.pk).stage == "provisioning"

    invitation = mail.outbox[-1]
    assert invitation.to == ["ada@example.test"]  # the verified external address, never the new mailbox
    path = LINK.search(invitation.body).group(1)
    done = applicant_post(path, {"password": CHOSEN, "confirm": CHOSEN})
    assert done.status_code == 200 and CHOSEN.encode() not in done.content
    run_worker()  # activation, then the welcome through the P2 sender
    app = Application.objects.get(pk=app.pk)
    assert app.stage == "active" and ProvisioningRequest.objects.get(pk=request.pk).status == "active"
    assert ApprovedMessage.objects.filter(application=app, kind="welcome").count() == 1
    assert cl.server.messages[-1]["rcpts"] == ["ada@example.test"]
    page = operator.get(screen(app)).content.decode()
    assert "Active; nothing more" in page and CHOSEN not in page

    # The applicant asks to leave: staff send the confirmation link, and the applicant confirms it.
    closer = logged_in(cl.closer.username)
    assert staff_post(closer, app, {"action": "withdrawal_link",
                                    "note": "Applicant asked by phone to withdraw"}).status_code == 302
    run_worker()
    withdraw_path = WITHDRAW_LINK.search(mail.outbox[-1].body).group(1)
    assert mail.outbox[-1].to == ["ada@example.test"]
    assert applicant_post(withdraw_path, {}).status_code == 200
    app = Application.objects.get(pk=app.pk)
    assert app.stage == "withdrawn"
    assert WithdrawalConfirmation.objects.get(application=app).state == "used"
    run_worker()  # the revocation round; its repeat waits out the settle delay, brought forward here
    PendingAction.objects.filter(kind="provision_revoke", status="queued").update(due_at=Now())
    run_worker()
    states = dict(AccessRevocation.objects.filter(request=request).values_list("kind", "state"))
    assert states["password_rotation"] == "applied_unverified" and states["setup_links"] == "verified"
    assert states["sessions"] == "unsupported"  # no documented mechanism: the owner decides (TEST-P5-18)
    assert FakeMailHost.current_passwords[("team.example.test", "ada.example")] != CHOSEN  # rotated
    assert ("team.example.test", "ada.example") in FakeMailHost.mailboxes  # the mailbox is kept (P5-D-9)
    calls = {c[0] for c in FakeMailHost.calls}
    assert not calls & {"delete_mailbox", "suspend"}
    page = closer.get(screen(app)).content.decode()
    assert "Not complete." in page and "Close the application" not in page  # final, never closed twice
    owner = logged_in(cl.approver.username)
    for kind in ("sessions", "app_credentials"):
        row = AccessRevocation.objects.get(request=request, kind=kind)
        assert staff_post(owner, app, {"action": "accept_exception", "revocation": str(row.public_id),
                                       "note": "No documented session revocation exists"}).status_code == 302
    assert "<p>Complete.</p>" in owner.get(screen(app)).content.decode()
    assert applicant_post_closed(withdraw_path)


def applicant_post_closed(path) -> bool:
    """A used link answers like any closed link."""
    return Client().get(path).status_code == 404


# --- TEST-P5-04 and TEST-P5-21: through the P2 inbound path --------------------------------------------------------

@pytest.fixture
def inbox(cl, tls, settings):
    """`cl` plus the scripted TLS IMAP server and a cursor from now, as in tests/test_inbound.py."""
    imap = ScriptedIMAP(tls=tls.good).start()
    settings.CATALYST_MAIL_CA_FILE = tls.ca
    settings.CATALYST_MAIL_IMAP_PORT = imap.port
    settings.CATALYST_MAIL_TRUSTED_AUTHSERV_ID = TRUSTED
    settings.CATALYST_MAIL_MAILBOX_REF = "applicants"
    settings.CATALYST_MAIL_COLLECT_FOLDER = "INBOX"
    settings.CATALYST_MAIL_SENT_FOLDER = ""
    settings.CATALYST_MAIL_POLL_SECONDS = 3600
    settings.CATALYST_MAIL_COLLECT_FAILURE_LIMIT = 3
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    cl.imap = imap
    cl.cursor = inbound.bootstrap_mailbox("from_now")
    yield cl
    imap.stop()


def test_p5_04_a_bounced_welcome_opens_a_staff_item(inbox, monkeypatch):
    app, _ = active_member(inbox, monkeypatch)
    welcome = ApprovedMessage.objects.get(application=app, kind="welcome")
    inbox.imap.deliver(bounce(welcome))
    collect()
    processed()
    received = InboundMessage.objects.get()
    assert received.classification == "bounce"
    assert StaffItem.objects.filter(application=app, reason_code="hard_bounce", status="open").exists()
    assert Application.objects.get(pk=app.pk).stage == "active"  # a bounce changes the record, not the membership


def test_p5_21_an_emailed_withdraw_only_creates_a_review_item(inbox, monkeypatch):
    app, request = active_member(inbox, monkeypatch)
    welcome = ApprovedMessage.objects.get(application=app, kind="welcome")
    inbox.imap.deliver(reply(welcome, body="Please withdraw my application and close my mailbox."))
    collect()
    processed()
    assert InboundMessage.objects.count() == 1
    app = Application.objects.get(pk=app.pk)
    assert app.stage == "active" and ProvisioningRequest.objects.get(pk=request.pk).status == "active"
    assert not WithdrawalConfirmation.objects.filter(application=app).exists()  # staff decide whether to send one
    assert not AccessRevocation.objects.filter(request=request).exists()
    received = InboundMessage.objects.get()
    assert (received.classification, received.status) == ("human", "awaiting_processing")  # a person's message
    assert StaffItem.objects.filter(application=app, reason_code="reply_needs_review", status="open").count() == 1


# --- negative controls: remove a critical gate and show the outcome is caught -----------------------------------

def test_p5_removed_gate_without_the_proof_of_ownership_revocation_would_rotate_someone_elses_mailbox(cl, monkeypatch):
    """With the gate, the foreign mailbox is never touched (test_closure). Removing only `proven_ours` makes the same
    close rotate it, so that one check is what protects someone else's mailbox."""
    from provisioning import closure
    from provisioning.adapter import Mailbox

    welcome_template(cl)
    app, _ = approved_request(cl, monkeypatch)
    FakeMailHost.mailboxes[("team.example.test", "ada.example")] = Mailbox("ada.example", "team.example.test", 50, 5, False)
    FakeMailHost.current_passwords[("team.example.test", "ada.example")] = "someone-elses"
    run_worker()  # a conflict: the mailbox is someone else's
    monkeypatch.setattr(closure, "proven_ours", lambda request: True)  # the gate, removed
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    run_worker()
    assert FakeMailHost.current_passwords[("team.example.test", "ada.example")] != "someone-elses"


def test_p5_removed_gate_without_the_screen_gate_each_service_still_refuses(cl, monkeypatch):
    """The screen's permission gate is only the first check. With only that gate removed (`admitted`), a dossier
    reader reaches the page, and every one of the screen's actions is still refused by its own service with
    `not_permitted`: nothing changes."""
    from provisioning import staff_views

    app = complete(cl, monkeypatch)
    release()
    request = request_of(app)
    reader = grant(cl, staff(cl, "dossier-reader-only"), "view_application")
    client = Client()
    client.force_login(reader)
    assert client.get(screen(app)).status_code == 403  # with the gate
    monkeypatch.setattr(staff_views, "admitted", lambda user: True)  # the gate, removed
    assert client.get(screen(app)).status_code == 200
    target = {"request": str(request.public_id), "note": "Reader trying this action"}
    forms = {
        "approve": {"request": str(request.public_id), "digest": request.approval_digest},
        "reserve_exception": {"local_part": "reader.choice", "note": "Reader trying this action"},
        "record_checklist": target, "attest": target, "supersede": target, "release_address": target,
        "reissue": target, "retry_activation": target, "recheck_revocation": target,
        "confirm_found": {**target, "decision": "ours"},
        "accept_exception": {"revocation": str(request.public_id), "note": "Reader trying this action"},
        "withdrawal_link": {"note": "Reader trying this action"},
        "close": {"outcome": "closed", "note": "Reader trying this action"},
    }
    assert set(forms) == set(staff_views.ACTIONS)  # every action the screen has
    act = reverse("provisioning_staff:act", args=[app.public_ref])
    for action, form in forms.items():
        response = client.post(act, {"action": action, **form})
        assert response.status_code == 409, action
        code = re.search(r"refused \((\w+)\)", response.content.decode()).group(1)
        assert code in ("not_permitted", "invalid_request"), (action, code)  # never past a service
        if action != "accept_exception":  # that id names no revocation: refused before its service
            assert code == "not_permitted", action
    assert request_of(app).status == "awaiting_approval" and Application.objects.get(pk=app.pk).stage == "provisioning"


# --- 5C traceability additions (the independent review) --------------------------------------------------------

def test_p5_01_only_the_owners_versioned_command_releases_and_nothing_starts_without_it(cl, monkeypatch):
    from django.core.management import CommandError, call_command

    app = complete(cl, monkeypatch)
    run_worker()
    assert not ProvisioningRequest.objects.filter(application=app).exists()  # agreements complete: still held
    assert PendingAction.objects.get(kind="provision").status == "held"
    for args in (("--activation-version", "99", "--approval-ref", "D-47"), ("--activation-version", "1",
                                                                             "--approval-ref", "")):
        with pytest.raises(CommandError):
            call_command("activate_provisioning", *args)
    assert not ProvisioningRequest.objects.filter(application=app).exists()


def test_p5_07_every_approved_component_changes_what_the_approver_confirms():
    from provisioning import core

    base = ("ada.example@team.example.test", 1024, 100, "api", "a" * 64)
    variants = [("bea.example@team.example.test", *base[1:]), (base[0], 2048, *base[2:]),
                (*base[:2], 99, *base[3:]), (*base[:3], "checklist", base[4]), (*base[:4], "b" * 64)]
    digests = {core.approval_digest(*v) for v in [base, *variants]}
    assert len(digests) == 6  # address, quota, limit, method and prerequisites are each bound
    assert core.approval_digest("ADA.Example@team.example.test", *base[1:]) == core.approval_digest(*base)


@pytest.mark.parametrize("cause", ["pause", "hard_bounce"])
def test_p5_02_a_broken_prerequisite_refuses_at_approval_at_the_password_set_and_at_activation(cl, monkeypatch, cause):
    from correspondence.staff_items import open_item
    from provisioning import services
    from tests.test_credentials import post
    from workflow.models import AutomationPause

    def breaks(app):
        if cause == "pause":
            return AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref,
                                                  reason="synthetic boundary check", actor_ref="t")
        return open_item("hard_bounce", f"boundary:{app.public_ref}", application=app)

    def repair(app, broken):
        if cause == "pause":
            AutomationPause.objects.filter(pk=broken.pk).delete()
        else:
            StaffItem.objects.filter(pk=broken.pk).update(status="resolved")

    # Approval boundary
    app = complete(cl, monkeypatch)
    release()
    request = request_of(app)
    broken = breaks(app)
    with pytest.raises(services.Refused, match="paused" if cause == "pause" else "hard_bounce_open"):
        services.approve(request.pk, cl.approver, request.approval_digest)
    repair(app, broken)
    services.approve(request.pk, cl.approver, request.approval_digest)

    # The password-set boundary: the applicant's link refuses while the prerequisite is broken
    welcome_template(cl)
    run_worker()
    request.refresh_from_db()
    path = LINK.search(mail.outbox[-1].body).group(1)
    broken = breaks(app)
    assert post(path).status_code == 404
    assert ("team.example.test", "ada.example") not in FakeMailHost.current_passwords
    repair(app, broken)
    assert post(path).status_code == 200

    # The activation boundary: the set is complete, but activation refuses until the cause is repaired
    broken = breaks(app)
    PendingAction.objects.filter(kind="provision_activate", status__in=("queued", "held")).update(due_at=Now())
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "provisioning"  # activation did not happen while broken
    if cause == "hard_bounce":  # an automated action runs and refuses at the boundary, with its reason
        refused = app.events.get(kind="provisioning_activation_refused")
        assert refused.data["reason"] == "hard_bounce_open"
    else:  # a pause holds the automated action: it never ran
        assert not app.events.filter(kind="provisioning_activation_refused").exists()
        assert PendingAction.objects.filter(kind="provision_activate", status__in=("queued", "held")).exists()
    repair(app, broken)
    from provisioning import credentials

    if Application.objects.get(pk=app.pk).stage != "active":  # a refused activation is retried once repaired
        credentials.retry_activation(request.pk, cl.op1, "The boundary cause was repaired")
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "active"


def test_p5_18_the_mail_host_adapter_has_no_delete_or_suspend_operation():
    """The adapter's public surface is pinned: removing a person's access can never delete a mailbox, suspend an
    account or touch a domain, because no such operation exists to call (P5-D-9)."""
    import inspect

    from provisioning.adapter import MailHost

    public = {name for name, _ in inspect.getmembers(MailHost, inspect.isfunction) if not name.startswith("_")}
    assert public == {"read", "create", "set_password", "list_forwarders", "delete_forwarder", "read_catch_all"}
    fake = {name for name, _ in inspect.getmembers(FakeMailHost, callable) if not name.startswith("_")}
    assert fake - {"reset"} == public  # the fake adds only its test reset


def test_p5_22_nothing_closes_an_application_for_want_of_a_response(cl, monkeypatch, settings):
    """Scope: the one P5 wait for the applicant, the password link. Expiry after expiry ends in a staff item with an
    owner, never a closure (P5-D-11). Earlier phases' reminder bounds are P2's (016)."""
    from datetime import timedelta

    from tests.test_credentials import invited

    settings.CATALYST_SETUP_INVITE_MAX_SERIES = 2
    app, request, _ = invited(cl, monkeypatch)
    from provisioning.models import CredentialSetup

    for _ in range(4):  # the applicant never answers: every link expires, sweep after sweep
        CredentialSetup.objects.filter(request=request, state__in=("invited", "presented")).update(
            expires_at=Now() - timedelta(seconds=1))
        PendingAction.objects.filter(status="queued").update(due_at=Now())
        run_worker()
    app = Application.objects.get(pk=app.pk)
    assert app.stage == "provisioning" and not app.events.filter(kind__in=("application_closed",
                                                                          "application_withdrawn")).exists()
    assert StaffItem.objects.filter(application=app, status="open",
                                    reason_code="provisioning_setup_needs_staff").exists()  # shown, with an owner


def test_p5_22_a_new_application_after_a_withdrawal_inherits_nothing(cl, monkeypatch):
    from provisioning import closure
    from tests.test_outbound import verified_application

    app, request = active_member(cl, monkeypatch)
    old_setup = request.setups.get()
    closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
    run_worker()
    again = verified_application(email="ada@example.test")
    assert again.pk != app.pk and again.stage not in ("withdrawn", "closed", "active", "provisioning")
    from provisioning.models import AddressReservation, CredentialSetup

    assert not ProvisioningRequest.objects.filter(application=again).exists()
    assert not AddressReservation.objects.filter(application=again).exists()
    assert not CredentialSetup.objects.filter(request__application=again).exists()
    assert not WithdrawalConfirmation.objects.filter(application=again).exists()
    assert Application.objects.get(pk=app.pk).stage == "withdrawn"  # the old case stays closed
    assert CredentialSetup.objects.get(pk=old_setup.pk).state == "completed"  # its history is kept
    # The old address stays held for the withdrawn case's revocation: the database refuses it to the new application,
    # so a new release could only propose a fresh address, approved afresh.
    from django.db import IntegrityError, transaction

    old = request.reservation
    assert old.released_at is None
    with pytest.raises(IntegrityError), transaction.atomic():
        AddressReservation.objects.create(application=again, local_part=old.local_part, domain=old.domain,
                                          basis="naming_rule")
    assert not ProvisioningRequest.objects.filter(application=again, approved_at__isnull=False).exists()
