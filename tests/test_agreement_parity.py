"""bgl.8 (034 section 2.3 rows 27 to 29, 31 to 33): the first-generation signing behaviour, selectable and off by
default. Distribution "service" creates and distributes the envelope with `distributionMethod: NONE` and the service
sends the signing link (the NDA's link mail, the User Agreement's branded cover) from approved templates; every envelope
carries the `/signing/return/` redirect; the completion sweep interval is a setting with 300 s as its default; the typed
details of a completed envelope are read back as an envelope-sourced details version that a staff correction (D-46)
supersedes; address-quality codes are computed on them and shown on the staff screen.

Everything runs against the local fake Documenso. The link mail goes to the local sink (`mail.outbox`); the link's
token is read from the fake and must appear in the mail and nowhere else.
"""

import json
import logging
import re
from types import SimpleNamespace

import pytest
from django.conf import settings as django_settings
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from psycopg import errors

from agreements import address_quality, completion, details, provider, services, signing_mail
from agreements.models import AgreementDetailsVersion, AgreementInstance, AgreementType
from applications.models import Application
from config import guards
from correspondence.models import MessageTemplate, MessageTemplateVersion, OutboundMessage, StaffItem
from tests.test_agreement_completion import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, issued, nda, p2, reads_now, reset_gate, run_worker, signing_gate,
    tls, ua_template,
)
from tests.test_agreement_screens import client_for
from tests.test_outbound import staff  # noqa: F401
from workflow.models import AutomationPause, PendingAction

SIGNING_HOST = "https://sign.example.test"
UA_LAYOUT = {
    "name": "ua_v24", "tolerance": 1.5,
    "fields": {
        "legal_name": {"kind": "TEXT", "page": 4, "x": 10, "y": 20},
        "residence": {"kind": "TEXT", "page": 4, "x": 10, "y": 25},
        "address_line1": {"kind": "TEXT", "page": 4, "x": 10, "y": 30},
        "address_line2": {"kind": "TEXT", "page": 4, "x": 10, "y": 35, "optional": True},
        "locality": {"kind": "TEXT", "page": 4, "x": 10, "y": 40},
        "region": {"kind": "TEXT", "page": 4, "x": 10, "y": 45, "optional": True},
        "postal_code": {"kind": "TEXT", "page": 4, "x": 10, "y": 50},
        "country": {"kind": "DROPDOWN", "page": 4, "x": 10, "y": 55},
        "phone": {"kind": "TEXT", "page": 4, "x": 60, "y": 20},
    },
}
# What a synthetic applicant types, at the layout's positions (a little off, within the tolerance): no real person.
TYPED = [("TEXT", 4, 10.4, 20.3, "Ada Synthetic"), ("TEXT", 4, 10.0, 25.6, "United States, Alabama"),
         ("TEXT", 4, 10.2, 30.1, "1 Example Street"), ("TEXT", 4, 10.1, 40.0, "Exampleville"),
         ("TEXT", 4, 10.0, 45.2, "AL"), ("TEXT", 4, 10.3, 50.4, "12345"), ("DROPDOWN", 4, 10.0, 55.0, "United States"),
         ("TEXT", 4, 60.2, 20.1, "+1 555 0100"),
         ("TEXT", 4, 40.0, 70.0, "a field of another layout, ignored")]
EXPECTED = {"legal_name": "Ada Synthetic", "residence": "United States, Alabama", "address_line1": "1 Example Street",
            "address_line2": "", "locality": "Exampleville", "region": "AL", "postal_code": "12345", "country": "United States",
            "phone": "+1 555 0100"}


@pytest.fixture
def s(h, settings):
    """`h` under distribution "service": the signing host, the seeded link templates (the reset truncated them), the
    User Agreement's read-back layout and the decider's details permission."""
    settings.CATALYST_AGREEMENT_DISTRIBUTION = "service"
    settings.CATALYST_AGREEMENT_SIGNING_BASE_URL = SIGNING_HOST
    settings.CATALYST_AGREEMENT_FIELD_LAYOUTS = {"user_agreement:1": UA_LAYOUT}
    signing_mail.SEED.create_templates(MessageTemplate, MessageTemplateVersion)
    grant(h, h.agreement_decider, "confirm_required_details")
    return h


def link_mails():
    return [m for m in mail.outbox if m.subject.startswith(("Please review and sign", "Your [company] User Agreement"))]


def token_of(env, envelope_id, index=0):
    return env.fake.envelopes[envelope_id]["recipients"][index]["token"]


def use_payload(env, n=0):
    call = env.fake.calls("POST", "/envelope/use")[n]
    return json.loads(re.search(rb"\r\n\r\n(\{.*\})\r\n--", call["body"], flags=re.S).group(1))


def type_fields(env, instance, entries=TYPED):
    env.fake.type_fields(instance.envelope_id, 0, entries)


def user_agreement(app):
    return AgreementInstance.objects.get(application=app, agreement_type__key="user_agreement")


def issue_user_agreement(env, monkeypatch):
    """The NDA signed and verified under the signing-only gate, so the advance issues the User Agreement."""
    app = issued(env, monkeypatch)
    signing_gate(env)
    env.fake.sign(nda(app).envelope_id)
    reads_now()
    return Application.objects.get(pk=app.pk), user_agreement(app)


# --- rows 27, 28: distribution NONE and the service-sent link and cover ---------------------------------------------

def test_bgl8_under_the_provider_distribution_nothing_changes_but_the_redirect(h, monkeypatch, settings):
    assert settings.CATALYST_AGREEMENT_DISTRIBUTION == "provider"  # the shipped default: today's behaviour (P4-D-4)
    app = issued(h, monkeypatch)
    override = use_payload(h)["override"]
    assert override["distributionMethod"] == "EMAIL" and override["emailSettings"] == dict(provider.EMAIL_SETTINGS)
    assert override["redirectUrl"] == settings.CATALYST_PUBLIC_BASE_URL + "/signing/return/" == provider.return_url()
    assert json.loads(h.fake.calls("POST", "/envelope/distribute")[0]["body"])["meta"]["distributionMethod"] == "EMAIL"
    assert [m["kind"] for m in h.fake.emails] == ["signing_request"]  # the provider mails the applicant
    assert not PendingAction.objects.filter(kind=signing_mail.KIND).exists() and not link_mails()
    # a queued link under the provider distribution (a mode change with work in flight) skips, never sends
    instance = nda(app)
    signing_mail.enqueue_signing_link(instance, 0)
    run_worker()
    assert PendingAction.objects.get(kind=signing_mail.KIND).status == "cancelled"
    assert app.events.filter(kind="agreement_link_send_skipped", data__reason="provider_distributes").exists()
    assert not link_mails()


def test_bgl8_under_the_service_distribution_the_provider_mails_nobody_and_the_service_sends_the_link(s, monkeypatch, caplog,
                                                                                                       settings):
    caplog.set_level(logging.DEBUG)
    # bgl.6 (parity integration): the link mail carries the configured sender's display name and Reply-To
    settings.CATALYST_FROM_DISPLAY_NAME, settings.CATALYST_REPLY_TO = "Synthetic Agreements", "agreements-synthetic@example.test"
    app = issued(s, monkeypatch)
    instance = nda(app)
    assert use_payload(s)["override"]["distributionMethod"] == "NONE"
    assert json.loads(s.fake.calls("POST", "/envelope/distribute")[0]["body"])["meta"]["distributionMethod"] == "NONE"
    assert s.fake.envelopes[instance.envelope_id]["status"] == "PENDING" and s.fake.emails == []  # issued, no provider mail
    assert instance.issue_status == "issued"
    token = token_of(s, instance.envelope_id)
    [message] = link_mails()
    assert message.to == [instance.recipients.get(who="applicant").email]
    assert message.subject == signing_mail.SEED.LINK_SUBJECT and "PLACEHOLDER WORDING" in message.body  # the draft, marked
    assert f"{SIGNING_HOST}/sign/{token}" in message.body and app.display_name in message.body
    assert message.extra_headers["Auto-Submitted"] == "auto-generated" and message.extra_headers["Message-ID"]
    assert message.from_email == f"Synthetic Agreements <{settings.DEFAULT_FROM_EMAIL}>"
    assert message.reply_to == ["agreements-synthetic@example.test"]
    row = OutboundMessage.objects.get(template_key="agreement_link_nda")
    assert row.status == "accepted" and row.recipient == message.to[0] and row.sent_at
    assert row.template_version.startswith("1:")
    sent = app.events.get(kind="agreement_link_sent")
    assert sent.data["type"] == "nda" and sent.data["series"] == 0 and sent.data["draft"] is True
    # the token and the link live in the mail alone: no event, record, staff item or log line carries them
    for event in app.events.all():
        assert token not in json.dumps(event.data)
    assert not OutboundMessage.objects.filter(message_id__contains=token).exists()
    assert all(token not in r.getMessage() for r in caplog.records)
    assert PendingAction.objects.get(kind=signing_mail.KIND).status == "done"
    assert PendingAction.objects.filter(kind="read_agreement", input_ref=str(instance.public_id)).exists()  # the sweep too


def test_bgl8_the_user_agreement_gets_the_branded_cover_with_its_own_link(s, monkeypatch):
    try:
        app, ua = issue_user_agreement(s, monkeypatch)
        assert ua.issue_status == "issued"
        # the provider sent no signing request for either envelope; only the NDA's completed copy (P4-D-14)
        assert [m["kind"] for m in s.fake.emails] == ["completed_copy"]
        cover = link_mails()[-1]
        assert cover.subject == signing_mail.SEED.COVER_SUBJECT and cover.to == [ua.recipients.get(who="applicant").email]
        assert f"{SIGNING_HOST}/sign/{token_of(s, ua.envelope_id)}" in cover.body
        assert "Schedule A" in cover.body and "full legal name" in cover.body  # what to type, and the Schedule A slots
        assert token_of(s, nda(app).envelope_id) not in cover.body  # never the other envelope's token
        assert OutboundMessage.objects.filter(template_key="agreement_link_user_agreement", status="accepted").count() == 1
        assert [m.subject for m in link_mails()] == [signing_mail.SEED.LINK_SUBJECT, signing_mail.SEED.COVER_SUBJECT]
    finally:
        reset_gate(s)


def test_bgl8_the_link_waits_while_paused_skips_once_signed_and_a_series_is_sent_once(s, monkeypatch):
    app = issued(s, monkeypatch)
    instance = nda(app)
    assert len(link_mails()) == 1
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    reminder = signing_mail.enqueue_signing_link(instance, 1)  # the signing reminder's seam (bgl.7): the same send, series 1
    assert signing_mail.enqueue_signing_link(instance, 1) is None  # a series is queued once
    run_worker()
    assert PendingAction.objects.get(pk=reminder.pk).status == "queued" and len(link_mails()) == 1  # paused: it waits
    from tests import support
    support.resume_pauses()
    run_worker()
    assert PendingAction.objects.get(pk=reminder.pk).status == "done" and len(link_mails()) == 2
    assert app.events.filter(kind="agreement_link_sent", data__series=1).exists()
    s.fake.sign(instance.envelope_id)
    reads_now()
    assert nda(app).signing_status == "signing_complete_verified"
    late = signing_mail.enqueue_signing_link(instance, 2)
    run_worker()
    assert PendingAction.objects.get(pk=late.pk).status == "cancelled" and len(link_mails()) == 2
    assert app.events.filter(kind="agreement_link_send_skipped", data__reason="already_signed_or_closed").exists()


def test_bgl8_a_signer_missing_from_the_envelope_or_a_changed_address_sends_nothing_and_tells_staff(s, monkeypatch):
    app = issued(s, monkeypatch)
    instance = nda(app)
    mail.outbox.clear()
    with s.fake._lock:  # the provider's view of the signer changed: no token for our applicant
        s.fake.envelopes[instance.envelope_id]["recipients"][0]["email"] = "someone-else@example.test"
    action = signing_mail.enqueue_signing_link(instance, 1)
    run_worker()
    assert PendingAction.objects.get(pk=action.pk).status == "failed" and not mail.outbox
    assert StaffItem.objects.filter(application=app, reason_code=signing_mail.LINK_SEND_FAILED, status="open").count() == 1
    assert app.events.filter(kind="agreement_link_send_refused", data__reason="signer_not_on_envelope").exists()
    # the handler never sends inside a transaction and never runs the provider read inside one
    from django.db import transaction
    claim = SimpleNamespace(id=action.pk, attempt=1, lease_token=None, input_ref=str(instance.public_id),
                            subject_id=app.public_ref, final=False)
    with transaction.atomic(), pytest.raises(RuntimeError, match="inside a transaction"):
        handler = signing_mail.SendSigningLink()
        handler.check = lambda c: signing_mail.Proceed(app.pk, instance.pk, instance.envelope_id, "x@example.test", "x", "nda", 1)
        handler.run(claim)


# --- row 29: the return page ------------------------------------------------------------------------------------------

def test_bgl8_the_return_page_is_public_static_and_carries_no_case_data(h, monkeypatch):
    app = issued(h, monkeypatch)
    assert reverse("signing_return") == provider.RETURN_PATH == "/signing/return/"
    probe = f"{provider.RETURN_PATH}?case={app.public_ref}&token=secret-probe-token&externalId={nda(app).external_key}"
    response = Client().get(probe)
    page = response.content.decode()
    assert response.status_code == 200 and "Thank you for signing" in page and 'name="viewport"' in page
    for leak in (str(app.public_ref), "secret-probe-token", nda(app).external_key, app.display_name, "CAT-"):
        assert leak not in page
    assert "no-store" in response["Cache-Control"] and response["Referrer-Policy"] == "no-referrer"
    assert Client().get(provider.RETURN_PATH).content == response.content  # the same page whatever is asked
    assert Client().post(provider.RETURN_PATH, {"x": "y"}).status_code == 405
    assert not response.cookies  # nothing set, nothing read
    exact = Client().get("/signing/return")  # the first generation's exact path answers the same page, no redirect
    assert reverse("signing_return_exact") == "/signing/return"
    assert exact.status_code == 200 and exact.content == response.content


# --- row 31: the sweep interval ---------------------------------------------------------------------------------------

def test_bgl8_the_sweep_interval_defaults_to_300_seconds_and_3600_stays_selectable(h, monkeypatch, settings):
    assert settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS == 300  # the production default (the first generation's poll)
    app = issued(h, monkeypatch)
    instance = nda(app)

    def due():
        read = PendingAction.objects.get(kind="read_agreement", input_ref=str(instance.public_id), status="queued")
        return (read.due_at - timezone.now()).total_seconds()
    assert 240 < due() <= 300
    settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS = 3600  # the earlier value, still selectable
    reads_now()  # the envelope is still pending: the read schedules the next one at the new interval
    assert 3540 < due() <= 3600
    settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS = 300
    reads_now()
    assert 240 < due() <= 300


# --- rows 32, 33: the details read-back and address quality -----------------------------------------------------------

def test_bgl8_typed_details_are_read_back_as_an_envelope_version_and_a_staff_correction_supersedes_it(s, monkeypatch):
    try:
        app, ua = issue_user_agreement(s, monkeypatch)
        ua_type = AgreementType.objects.get(key="user_agreement")
        assert not AgreementDetailsVersion.objects.filter(application=app).exists()
        type_fields(s, ua)
        s.fake.sign(ua.envelope_id)
        reads_now()
        ua.refresh_from_db()
        assert ua.signing_status == "signing_complete_verified"
        row = AgreementDetailsVersion.objects.get(application=app, agreement_type=ua_type)
        assert (row.version, row.source, row.status, row.instance_id) == (1, "envelope", "confirmed", ua.pk)
        assert row.values == EXPECTED and row.values_sha256 == services._details_digest(EXPECTED)
        assert row.recorded_by == f"envelope:{ua.public_id}" and row.confirmed_by == f"signature:{ua.public_id}" and row.confirmed_at
        captured = app.events.get(kind="agreement_details_captured")
        assert captured.data == {"instance": str(ua.public_id), "type": "user_agreement", "version": 1, "layout": "ua_v24", "flags": []}
        for event in app.events.all():  # identifiers and codes only, never a typed value
            assert "Ada Synthetic" not in json.dumps(event.data) and "12345" not in json.dumps(event.data)
        assert not StaffItem.objects.filter(application=app, reason_code__in=(details.READBACK_INCOMPLETE, details.ADDRESS_QUALITY)).exists()
        assert completion.latest_details_ref(app, ua_type) == str(row.public_id)
        assert completion.details_confirmed(app, ua_type)  # no configured field list: the read-back is never a gate
        # a second verifying read records nothing more (one envelope read per instance)
        completion.enqueue_read(ua)
        reads_now()
        assert AgreementDetailsVersion.objects.filter(application=app).count() == 1
        # D-46: the staff correction is a later version, recorded then confirmed; the envelope version stays as read
        with pytest.raises(services.Refused, match="fields_mismatch"):
            services.record_required_details(app.pk, "user_agreement", {"postal_code": "54321"}, s.agreement_decider)
        with pytest.raises(services.PermissionDenied):
            services.record_required_details(app.pk, "user_agreement", dict(EXPECTED, postal_code="54321"), s.template_owner)
        draft = services.record_required_details(app.pk, "user_agreement", dict(EXPECTED, postal_code="54321"), s.agreement_decider)
        assert (draft.version, draft.source, draft.status, draft.instance_id) == (2, "staff", "draft", None)
        assert completion.latest_details_ref(app, ua_type) == str(row.public_id)  # a draft supersedes nothing yet
        services.confirm_required_details(draft.pk, s.agreement_decider, draft.values_sha256)
        assert completion.latest_details_ref(app, ua_type) == str(draft.public_id)
        assert AgreementDetailsVersion.objects.get(pk=row.pk).values == EXPECTED
        owner = s.committed.connect("owner", autocommit=True)
        for sql in ("UPDATE agreements_agreementdetailsversion SET values = '{}' WHERE id = %s",
                    "UPDATE agreements_agreementdetailsversion SET source = 'staff', instance_id = NULL WHERE id = %s",
                    "DELETE FROM agreements_agreementdetailsversion WHERE id = %s"):
            with pytest.raises(errors.InsufficientPrivilege):  # frozen for every role, the new columns included
                owner.execute(sql, [row.pk])
        with pytest.raises(errors.CheckViolation):  # an envelope version names its envelope
            owner.execute("INSERT INTO agreements_agreementdetailsversion (public_id, application_id, agreement_type_id, version,"
                          ' "values", values_sha256, status, recorded_by, confirmed_by, source, created_at)'
                          " VALUES (gen_random_uuid(), %s, %s, 9, '{}', '', 'draft', 'x', '', 'envelope', now())",
                          [app.pk, ua_type.pk])
    finally:
        reset_gate(s)


def test_bgl8_an_incomplete_read_back_records_nothing_opens_a_staff_item_and_never_holds_the_agreement(s, monkeypatch):
    try:
        app, ua = issue_user_agreement(s, monkeypatch)
        type_fields(s, ua, [e for e in TYPED if e[4] not in ("12345", "United States")])  # no postal code, no country
        s.fake.sign(ua.envelope_id)
        reads_now()
        ua.refresh_from_db()
        assert ua.signing_status == "signing_complete_verified"  # the signed agreement is the record; the read-back is not a gate
        assert not AgreementDetailsVersion.objects.filter(application=app).exists()
        assert StaffItem.objects.filter(application=app, reason_code=details.READBACK_INCOMPLETE, status="open").count() == 1
        incomplete = app.events.get(kind="agreement_details_readback_incomplete")
        assert incomplete.data["missing"] == ["country", "postal_code"] and incomplete.data["recipient_identified"] is True
        # staff record the details from the signed copy (D-46): the layout's fields, as a staff version, then confirmed
        page = client_for(s.agreement_decider).get(reverse("agreements_staff:agreements", args=[app.public_ref])).content.decode()
        assert "No confirmed version yet" in page and 'name="field-country"' in page
        with pytest.raises(services.Refused, match="fields_mismatch"):
            services.record_required_details(app.pk, "user_agreement", {"country": "x"}, s.agreement_decider)
        draft = services.record_required_details(app.pk, "user_agreement", EXPECTED, s.agreement_decider)
        assert (draft.version, draft.source, draft.status) == (1, "staff", "draft")
        services.confirm_required_details(draft.pk, s.agreement_decider, draft.values_sha256)
        assert completion.latest_details_ref(app, AgreementType.objects.get(key="user_agreement")) == str(draft.public_id)
    finally:
        reset_gate(s)


def test_bgl8_no_layout_reads_nothing_back_and_an_unreadable_field_list_is_a_provider_error(s, monkeypatch, settings):
    try:
        settings.CATALYST_AGREEMENT_FIELD_LAYOUTS = {}
        app, ua = issue_user_agreement(s, monkeypatch)
        type_fields(s, ua)
        s.fake.sign(ua.envelope_id)
        field_reads = []
        monkeypatch.setattr(provider, "read_fields", lambda envelope_id: field_reads.append(envelope_id) or ())
        reads_now()
        assert user_agreement(app).signing_status == "signing_complete_verified"
        assert not AgreementDetailsVersion.objects.filter(application=app).exists()
        assert field_reads == []  # no layout: the typed fields are never even read
    finally:
        reset_gate(s)
    assert provider.typed_fields({"fields": [{"type": "TEXT", "inserted": True, "page": 1, "positionX": 1, "positionY": 2,
                                              "customText": "x" * 900, "recipientId": 5},
                                             {"type": "SIGNATURE", "inserted": True, "page": 1, "positionX": 1, "positionY": 2},
                                             {"type": "TEXT", "inserted": False, "page": 1, "positionX": 1, "positionY": 2, "customText": "n"},
                                             {"type": "TEXT", "inserted": True, "page": "1", "positionX": 1, "positionY": 2, "customText": "n"},
                                             "junk"]}) == (
        provider.TypedField(5, "TEXT", 1, 1.0, 2.0, "x" * provider.MAX_FIELD_TEXT),)
    with pytest.raises(provider.ProviderError, match="response_unreadable"):
        provider.typed_fields({"fields": "not a list"})
    assert "Synthetic-Typed-Value" not in repr(provider.TypedField(5, "TEXT", 1, 1.0, 2.0, "Synthetic-Typed-Value"))  # never the text


def test_bgl8_address_quality_codes_and_the_staff_screen_shows_them(s, monkeypatch):
    flags = address_quality.flags
    assert flags(EXPECTED) == ()
    assert flags(dict(EXPECTED, address_line1="1 St", locality="X", region="", postal_code="12345")) == ("short",)
    assert flags(dict(EXPECTED, country="")) == ("no_country",)
    assert flags(dict(EXPECTED, postal_code="1234")) == ("postal_code_invalid",)
    assert flags(dict(EXPECTED, postal_code="NONE")) == ("no_postal_code",)
    assert flags(dict(EXPECTED, postal_code="")) == ("no_postal_code",)
    assert flags(dict(EXPECTED, country="CA", postal_code="K1A 0B1")) == ()
    assert flags(dict(EXPECTED, country="United Kingdom", postal_code="SW1A 1AA")) == ()
    assert flags(dict(EXPECTED, country="Germany", postal_code="1234")) == ("postal_code_invalid",)
    assert flags(dict(EXPECTED, country="Netherlands", postal_code="1234 AB")) == ()
    assert flags(dict(EXPECTED, country="United Arab Emirates", postal_code="NONE")) == ()
    assert flags(dict(EXPECTED, country="Exampleland", postal_code="XYZ")) == ("postal_code_unchecked",)
    assert address_quality.problems(dict(EXPECTED, country="Exampleland")) == ()  # advisory, never a problem
    assert flags({}) == ("short", "no_country")
    try:
        app, ua = issue_user_agreement(s, monkeypatch)
        type_fields(s, ua, [(k, p, x, y, "1234" if t == "12345" else t) for k, p, x, y, t in TYPED])  # a bad US postal code
        s.fake.sign(ua.envelope_id)
        reads_now()
        assert app.events.get(kind="agreement_details_captured").data["flags"] == ["postal_code_invalid"]
        assert StaffItem.objects.filter(application=app, reason_code=details.ADDRESS_QUALITY, status="open").count() == 1
        assert completion.details_confirmed(app, AgreementType.objects.get(key="user_agreement"))  # a flag never blocks
        page = client_for(s.agreement_decider).get(reverse("agreements_staff:agreements", args=[app.public_ref]))
        html = page.content.decode()
        assert page.status_code == 200 and "Details from the signed user_agreement" in html
        assert "<code>postal_code_invalid</code>" in html and "read back from the signed agreement" in html
        assert 'name="field-postal_code"' in html and "Correct the details (D-46)" in html
        # the correction through the screen: a draft, then its confirmation
        response = client_for(s.agreement_decider).post(reverse("agreements_staff:act", args=[app.public_ref]), {
            "action": "record_details", "type": "user_agreement",
            **{f"field-{k}": v for k, v in dict(EXPECTED, postal_code="12345").items()}})
        assert response.status_code == 302
        draft = AgreementDetailsVersion.objects.get(application=app, version=2)
        response = client_for(s.agreement_decider).post(reverse("agreements_staff:act", args=[app.public_ref]), {
            "action": "confirm_details", "details": str(draft.public_id), "digest": draft.values_sha256})
        assert response.status_code == 302 and AgreementDetailsVersion.objects.get(pk=draft.pk).status == "confirmed"
        html = client_for(s.agreement_decider).get(reverse("agreements_staff:agreements", args=[app.public_ref])).content.decode()
        assert "Version 2 (staff" in html and "no flags" in html
    finally:
        reset_gate(s)


# --- the guards ---------------------------------------------------------------------------------------------------------

def test_bgl8_the_distribution_and_layout_settings_are_guarded():
    def problems(env="test", environ=None, **values):
        return guards.agreement_problems(SimpleNamespace(CATALYST_ENV=env, **values), environ or {})
    assert problems() == [] and problems(env="production") == []  # the defaults: provider distribution, no layouts
    assert any("'provider' or 'service'" in p for p in problems(CATALYST_AGREEMENT_DISTRIBUTION="both"))
    assert any("SIGNING_BASE_URL is required" in p for p in problems(CATALYST_AGREEMENT_DISTRIBUTION="service"))
    assert problems(CATALYST_AGREEMENT_DISTRIBUTION="service", CATALYST_AGREEMENT_SIGNING_BASE_URL=SIGNING_HOST) == []
    for bad in ("http://sign.example.test", "https://sign.example.test/api", "https://sign.example.test/?x=1", "sign.example.test"):
        assert any("https with a host and nothing else" in p for p in problems(CATALYST_AGREEMENT_SIGNING_BASE_URL=bad)), bad
    assert any("may not be set from the environment" in p
               for p in problems(environ={"CATALYST_AGREEMENT_DISTRIBUTION": "service"}))
    assert any("may not be set from the environment" in p
               for p in problems(environ={"CATALYST_AGREEMENT_FIELD_LAYOUTS": "{}"}))
    assert problems(CATALYST_AGREEMENT_FIELD_LAYOUTS={"user_agreement:1": UA_LAYOUT}) == []
    for bad, expected in (({"user_agreement": UA_LAYOUT}, "<type key>:<template version>"),
                          ({"user_agreement:1": {"fields": UA_LAYOUT["fields"]}}, "has a name"),
                          ({"user_agreement:1": {"name": "x", "fields": {}}}, "non-empty mapping"),
                          ({"user_agreement:1": {"name": "x", "tolerance": 50, "fields": UA_LAYOUT["fields"]}}, "between 0 and 10"),
                          ({"user_agreement:1": {"name": "x", "fields": {"legal_name": {"kind": "SIGNATURE", "page": 1, "x": 1, "y": 1}}}}, "kind TEXT or DROPDOWN"),
                          ({"user_agreement:1": {"name": "x", "fields": {"legal_name": {"kind": "TEXT", "page": 0, "x": 1, "y": 1}}}}, "page >= 1"),
                          ({"user_agreement:1": {"name": "x", "fields": {"legal_name": {"kind": "TEXT", "page": 1, "x": 101, "y": 1}}}}, "page percentages"),
                          ({"user_agreement:1": {"name": "x", "fields": {"not an identifier!": {"kind": "TEXT", "page": 1, "x": 1, "y": 1}}}}, "identifiers")):
        assert any(expected in p for p in problems(CATALYST_AGREEMENT_FIELD_LAYOUTS=bad)), (bad, expected)
    # synthetic only: a live environment refuses the signing host and the layouts until the owner's decision (POL-18)
    assert any("allowed only in the test and staging" in p for p in problems(env="production", CATALYST_AGREEMENT_SIGNING_BASE_URL=SIGNING_HOST))
    assert any("allowed only in the test and staging" in p
               for p in problems(env="production", CATALYST_AGREEMENT_FIELD_LAYOUTS={"user_agreement:1": UA_LAYOUT}))
    assert django_settings.CATALYST_ACTION_HANDLERS["send_signing_link"] == "agreements.signing_mail.SendSigningLink"
    assert signing_mail.SendSigningLink.automated and signing_mail.SendSigningLink.redeliverable


# --- bgl.11 x bgl.8 (parity integration): the HTML part and the first name -----------------------------------------

def link_version(env, key, body, page, subject_reference=False):
    from correspondence import outbound
    from correspondence.rendering import version_digest
    from correspondence.roles import TEMPLATE_OWNER

    template = MessageTemplate.objects.get(key=key)
    subject = f"Synthetic {key}"
    version = MessageTemplateVersion.objects.create(
        template=template, version=template.versions.count() + 1, subject=subject, body_text=body, body_html=page,
        variables=["first_name", "link"], secret_bearing=True, subject_reference=subject_reference,
        content_sha256=version_digest(subject, body, page, subject_reference=subject_reference))
    outbound.approve_template_version(version.pk, staff(env, f"link-owner-{key}", TEMPLATE_OWNER))
    return version


@pytest.mark.parametrize("subject_reference", [False, True])
def test_bgl11_the_signing_link_and_the_cover_are_sent_multipart_and_greet_by_first_name(s, monkeypatch, subject_reference):
    import html

    body, page = "Hello $first_name,\nSign here: $link\n", '<p>Hello $first_name,</p><p><a href="$link">Sign</a></p>\n'
    for key in ("agreement_link_nda", "agreement_link_user_agreement"):
        link_version(s, key, body, page, subject_reference)
    try:
        app, ua = issue_user_agreement(s, monkeypatch)
        first = app.display_name.split()[0]
        sent = [m for m in mail.outbox if "/sign/" in m.body]
        suffix = f" [{app.reference}]" if subject_reference else ""
        assert [m.subject for m in sent] == ["Synthetic agreement_link_nda" + suffix, "Synthetic agreement_link_user_agreement" + suffix]
        for message, envelope_id in zip(sent, (nda(app).envelope_id, ua.envelope_id)):
            link = f"{SIGNING_HOST}/sign/{token_of(s, envelope_id)}"
            assert message.body == f"Hello {first},\nSign here: {link}\n"
            assert [tuple(a) for a in message.alternatives] == [
                (f'<p>Hello {html.escape(first)},</p><p><a href="{link}">Sign</a></p>\n', "text/html")]
            wire = message.message()
            assert wire.get_content_type() == "multipart/alternative"
            assert [part.get_content_type() for part in wire.get_payload()] == ["text/plain", "text/html"]
    finally:
        reset_gate(s)
