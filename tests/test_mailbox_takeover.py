"""bgl.6 (034 rows 10 and 22, section 3.2; the owner's answer of 2026-10-31): v2 sends every applicant mail with the
configured display name and Reply-To; production may lift the first-generation mailbox denial at the swap, and then
must read the mailbox it sends from; a reply to a first-generation thread associates through an optional resolver; and
the collection cursor starts where the first generation's poller stopped instead of reprocessing the inbox.

Synthetic only: `example.test` addresses, loopback scripted SMTP and IMAP servers, a fake resolver standing in for the
first-generation import's (tests/foreign_threads_fake.py).
"""

import email
import hashlib
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.mail import EmailMessage, get_connection
from django.core.management import CommandError, call_command

from applications.models import Application
from config import guards
from correspondence import inbound
from correspondence.models import InboundMessage, InboundMessageLocation, MailboxCursor, StaffItem
from provisioning import closure
from tests import foreign_threads_fake as fake
from tests.support import run
from tests.test_closure import cl  # noqa: F401  (fixture)
from tests.test_credentials import invited, post
from tests.test_guards import LEGACY_DIGEST, live
from tests.test_hold_and_resend import submit
from tests.test_inbound import TRUSTED, collect, mailbox, reply, sent_question, tls  # noqa: F401  (fixtures and helpers)
from tests.test_outbound import ask, ready, run_worker  # noqa: F401  (fixture chain)
from tests.test_provisioning import (  # noqa: F401  (fixture chain)
    a, c, d, ev, g, h, k, p2, pv,
)
from tests.test_startup import CHECK, PRODUCTION
from tests.imap_server import ScriptedIMAP

SENDER = "agreements-synthetic@example.test"
NAME = "Synthetic Agreements"
FORMATTED = f"{NAME} <{SENDER}>"
LEGACY = "legacy-synthetic@example.test"  # tests.test_guards: LEGACY_DIGEST is its digest


def named_sender(settings, name=NAME, reply_to=SENDER):
    settings.DEFAULT_FROM_EMAIL, settings.CATALYST_FROM_DISPLAY_NAME, settings.CATALYST_REPLY_TO = SENDER, name, reply_to


def envelope_sender(sent) -> str:
    """The scripted server keeps the raw MAIL FROM line: the address between the angle brackets, nothing else."""
    line = sent["from"].strip()
    assert line.lower().startswith("mail from:<") and line.endswith(">"), line
    return line[len("mail from:<"):-1]


def headers_of(data: bytes):
    return email.message_from_bytes(data)


# --- the sender headers on every applicant mail ------------------------------------------------------------------

def test_bgl6_the_p2_sender_and_the_verification_mail_carry_the_display_name_and_reply_to(ready, settings):
    named_sender(settings)
    ask(ready)
    run_worker()
    sent = ready.server.messages[-1]
    parsed = headers_of(sent["data"])
    assert parsed["From"] == FORMATTED and parsed["Reply-To"] == SENDER
    assert envelope_sender(sent) == SENDER  # the envelope sender is the bare address
    submit("grace@example.test")
    run_worker()
    confirmation = mail.outbox[-1]
    assert confirmation.to == ["grace@example.test"]
    assert confirmation.from_email == FORMATTED and confirmation.reply_to == [SENDER]
    parsed = headers_of(confirmation.message().as_bytes())
    assert parsed["From"] == FORMATTED and parsed["Reply-To"] == SENDER


def test_bgl6_unset_the_headers_are_todays_bare_address_and_no_reply_to(ready, settings):
    assert settings.CATALYST_FROM_DISPLAY_NAME == "" and settings.CATALYST_REPLY_TO == ""  # the defaults
    ask(ready)
    run_worker()
    parsed = headers_of(ready.server.messages[-1]["data"])
    assert parsed["From"] == settings.DEFAULT_FROM_EMAIL and parsed["Reply-To"] is None
    submit("grace@example.test")
    run_worker()
    confirmation = mail.outbox[-1]
    assert confirmation.from_email == settings.DEFAULT_FROM_EMAIL and confirmation.reply_to == []
    assert "Reply-To" not in confirmation.message()


def test_bgl6_the_setup_welcome_and_withdrawal_mails_carry_the_display_name_and_reply_to(cl, monkeypatch, settings):  # noqa: F811
    named_sender(settings)
    app, _, path = invited(cl, monkeypatch)
    setup = mail.outbox[-1]
    assert setup.to == ["ada@example.test"] and setup.from_email == FORMATTED and setup.reply_to == [SENDER]
    assert post(path).status_code == 200
    run_worker()  # activation, then the welcome through the P2 sender
    assert Application.objects.get(pk=app.pk).stage == "active"
    welcome = cl.server.messages[-1]
    assert welcome["rcpts"] == ["ada@example.test"] and envelope_sender(welcome) == SENDER
    parsed = headers_of(welcome["data"])
    assert parsed["From"] == FORMATTED and parsed["Reply-To"] == SENDER
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked to withdraw by email")
    run_worker()
    withdrawal = mail.outbox[-1]
    assert "/withdraw/" in withdrawal.body
    assert withdrawal.from_email == FORMATTED and withdrawal.reply_to == [SENDER]


def test_bgl6_the_django_transport_sends_a_named_sender_from_the_bare_envelope_address(p2):  # noqa: F811
    message = EmailMessage(subject="s", body="b", from_email=FORMATTED, to=["ada@example.test"], reply_to=[SENDER],
                           connection=get_connection(guards.TRANSPORT_EMAIL_BACKEND))
    assert message.send(fail_silently=False) == 1
    [sent] = p2.server.messages
    assert envelope_sender(sent) == SENDER
    parsed = headers_of(sent["data"])
    assert parsed["From"] == FORMATTED and parsed["Reply-To"] == SENDER


def test_bgl6_the_sender_settings_are_checked_at_start_up():
    def problems(**values):
        base = dict(CATALYST_ENV="test", DEFAULT_FROM_EMAIL=SENDER, CATALYST_FROM_DISPLAY_NAME="", CATALYST_REPLY_TO="")
        return guards.sender_problems(SimpleNamespace(**{**base, **values}))

    assert problems() == [] and problems(CATALYST_FROM_DISPLAY_NAME=NAME, CATALYST_REPLY_TO=SENDER) == []
    assert problems(CATALYST_REPLY_TO="replies-synthetic@example.test") == []  # outside a live environment any address
    for bad in ("Line\r\nBcc: x@example.test", "Name <x@example.test>", "Name@example.test", 'Quo"te', "Back\\slash",
                "x" * 65, " padded", "tab\tname"):
        assert any("CATALYST_FROM_DISPLAY_NAME" in p for p in problems(CATALYST_FROM_DISPLAY_NAME=bad)), bad
    for bad in ("not-an-address", "a@example.test, b@example.test", "Name <a@example.test>", "a b@example.test"):
        assert any("CATALYST_REPLY_TO must be one plain address" in p for p in problems(CATALYST_REPLY_TO=bad)), bad
    assert any("CATALYST_FROM_EMAIL must be one plain address" in p for p in problems(DEFAULT_FROM_EMAIL=FORMATTED))
    live_problems = problems(CATALYST_ENV="production", CATALYST_REPLY_TO="replies-synthetic@example.test")
    assert any("must be the CATALYST_FROM_EMAIL address in a live environment" in p for p in live_problems)
    assert problems(CATALYST_ENV="production", CATALYST_REPLY_TO=SENDER.upper()) == []


# --- the first-generation guard and the swap value ---------------------------------------------------------------

def test_bgl6_the_first_generation_login_is_denied_until_the_swap_value_lifts_it():
    legacy = dict(CATALYST_MAIL_USER=LEGACY, CATALYST_MAIL_USER_SHA256=LEGACY_DIGEST, DEFAULT_FROM_EMAIL=LEGACY)
    before = guards.mail_problems(live(**legacy))
    assert any("CATALYST_MAIL_USER is a denied mailbox" in p for p in before)
    assert any("names a denied mailbox" in p for p in before)
    swapped = guards.mail_problems(live(**legacy, CATALYST_MAIL_TAKEOVER=guards.MAIL_TAKEOVER_VALUE))
    assert swapped == []
    # The denied list stays required and configured: unsetting the value restores the refusal.
    assert any("must list the first-generation mailbox" in p
               for p in guards.mail_problems(live(**legacy, CATALYST_MAIL_DENIED_USER_SHA256=[],
                                                  CATALYST_MAIL_TAKEOVER=guards.MAIL_TAKEOVER_VALUE)))
    for value in ("yes", "1", "first-generation-poll-stopped ", "FIRST-GENERATION-POLL-STOPPED"):
        refused = guards.mail_problems(live(**legacy, CATALYST_MAIL_TAKEOVER=value))
        assert any("CATALYST_MAIL_TAKEOVER must be empty or exactly" in p for p in refused), value
        assert any("denied mailbox" in p for p in refused), value  # a wrong value lifts nothing
    assert LEGACY not in " ".join(before + refused)  # messages name settings, never a mailbox


def test_bgl6_under_the_swap_v2_must_read_the_mailbox_it_sends_from():
    takeover = dict(CATALYST_MAIL_TAKEOVER=guards.MAIL_TAKEOVER_VALUE, CATALYST_MAIL_USER_SHA256=LEGACY_DIGEST)
    # The worker: its login is another mailbox than the sender's.
    worker = guards.mail_problems(live(**takeover, CATALYST_MAIL_USER=LEGACY, DEFAULT_FROM_EMAIL=SENDER))
    assert any("CATALYST_MAIL_USER must be the CATALYST_FROM_EMAIL mailbox" in p for p in worker)
    # The web process holds no login, only the pin: the pin must be the sender's digest.
    web = guards.mail_problems(live(**takeover, CATALYST_MAIL_USER="", DEFAULT_FROM_EMAIL=SENDER))
    assert any("CATALYST_MAIL_USER_SHA256 must pin the CATALYST_FROM_EMAIL mailbox" in p for p in web)
    assert guards.mail_problems(live(**takeover, CATALYST_MAIL_USER="", DEFAULT_FROM_EMAIL=LEGACY.upper())) == []
    # Outside a live environment the login is still compared (there is no pin).
    local = SimpleNamespace(CATALYST_ENV="test", CATALYST_MAIL_HOST="127.0.0.1", CATALYST_MAIL_TLS="none",
                            CATALYST_MAIL_USER="synthetic-user", DEFAULT_FROM_EMAIL=SENDER,
                            CATALYST_MAIL_TAKEOVER=guards.MAIL_TAKEOVER_VALUE)
    assert any("CATALYST_MAIL_USER must be the CATALYST_FROM_EMAIL mailbox" in p for p in guards.mail_problems(local))
    # Without the swap value nothing compares them (v2's own mailbox before the swap).
    assert guards.takeover_problems(live(CATALYST_MAIL_USER="synthetic-user", DEFAULT_FROM_EMAIL=SENDER)) == []


AGREEMENTS = "agreements@catalyst-v2.example.test"  # a production-shaped sender (live_problems refuses example.*)
AGREEMENTS_DIGEST = hashlib.sha256(AGREEMENTS.encode()).hexdigest()
SWAPPED = {**PRODUCTION, "CATALYST_FROM_EMAIL": AGREEMENTS, "CATALYST_MAIL_USER_SHA256": AGREEMENTS_DIGEST,
           "CATALYST_MAIL_DENIED_USER_SHA256": AGREEMENTS_DIGEST, "CATALYST_FROM_DISPLAY_NAME": NAME,
           "CATALYST_REPLY_TO": AGREEMENTS, "CATALYST_MAIL_TAKEOVER": guards.MAIL_TAKEOVER_VALUE}


@pytest.mark.parametrize(("overrides", "message"), [
    ({}, None),
    ({"CATALYST_MAIL_TAKEOVER": None}, "names a denied mailbox"),
    ({"CATALYST_FROM_EMAIL": "onboarding@catalyst-v2.example.test", "CATALYST_REPLY_TO": None},
     "CATALYST_MAIL_USER_SHA256 must pin the CATALYST_FROM_EMAIL mailbox under CATALYST_MAIL_TAKEOVER"),
    ({"CATALYST_REPLY_TO": "replies@catalyst-v2.example.test"}, "CATALYST_REPLY_TO must be the CATALYST_FROM_EMAIL address"),
    ({"CATALYST_MAIL_TAKEOVER": "yes"}, "CATALYST_MAIL_TAKEOVER must be empty or exactly"),
], ids=["swapped", "no-swap-value", "reader-is-not-the-sender", "reply-to-elsewhere", "wrong-value"])
def test_bgl6_production_starts_after_the_swap_only_reading_the_mailbox_it_sends_from(overrides, message):
    result = run(CHECK, **{**SWAPPED, **overrides})
    if message is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0 and message in result.stderr, result.stderr
    assert AGREEMENTS not in result.stderr


# --- replies to first-generation threads ---------------------------------------------------------------------------

V1_ID = "<v1-synthetic-0001@agreements.synthetic.example.test>"


@pytest.fixture
def resolver(settings):
    fake.reset()
    settings.CATALYST_FOREIGN_THREAD_RESOLVER = "tests.foreign_threads_fake"
    yield fake
    fake.reset()


def only_inbound():
    [message] = InboundMessage.objects.all()
    return message


def test_bgl6_a_reply_to_a_first_generation_message_id_associates_and_is_processed_as_a_reply(mailbox, resolver):
    resolver.MESSAGE_IDS[V1_ID] = mailbox.app.pk
    mailbox.imap.deliver(reply(None, in_reply_to=V1_ID, subject="Re: your request"))
    collect()
    message = only_inbound()
    assert (message.application_id, message.approved_message_id) == (mailbox.app.pk, None)
    assert (message.classification, message.trust_decision) == ("human", "trusted")
    assert StaffItem.objects.filter(reason_code="reply_needs_review", application=mailbox.app).count() == 1
    assert not StaffItem.objects.filter(reason_code="unmatched").exists()
    assert resolver.CALLS[0] == ("message_ids", [V1_ID])


def test_bgl6_a_first_generation_subject_reference_associates_when_no_message_id_matches(mailbox, resolver):
    resolver.REFERENCES["CAT-AB12-CD34"] = mailbox.app.pk
    mailbox.imap.deliver(reply(None, in_reply_to="<unknown@elsewhere.example.test>",
                               subject="Re: [CAT-AB12-CD34] Your Catalyst request"))
    collect()
    message = only_inbound()
    assert message.application_id == mailbox.app.pk and message.trust_decision == "trusted"
    assert [kind for kind, _ in resolver.CALLS] == ["message_ids", "subject"]


def test_bgl6_trust_rules_are_unchanged_for_a_first_generation_reply(mailbox, resolver):
    resolver.MESSAGE_IDS[V1_ID] = mailbox.app.pk
    mailbox.imap.deliver(reply(None, in_reply_to=V1_ID, sender="mallory@example.test"))
    collect()
    message = only_inbound()
    assert message.application_id == mailbox.app.pk  # associated, never trusted
    assert (message.status, message.exception_reason, message.trust_decision) == ("exception", "sender_mismatch",
                                                                                   "sender_mismatch")


def test_bgl6_no_match_or_no_resolver_keeps_the_unmatched_item_for_staff(mailbox, resolver, settings):
    mailbox.imap.deliver(reply(None, in_reply_to=V1_ID, subject="Re: [CAT-ZZ99-ZZ99] nothing imported"))
    collect()
    assert (only_inbound().status, only_inbound().exception_reason, only_inbound().application_id) == (
        "exception", "unmatched", None)
    settings.CATALYST_FOREIGN_THREAD_RESOLVER = ""  # the default without the first-generation app
    resolver.MESSAGE_IDS[V1_ID] = mailbox.app.pk
    calls = len(resolver.CALLS)
    mailbox.imap.deliver(reply(None, in_reply_to=V1_ID))
    collect()
    newest = InboundMessage.objects.order_by("-id").first()
    assert (newest.exception_reason, newest.application_id) == ("unmatched", None)
    assert len(resolver.CALLS) == calls  # nothing was asked


def test_bgl6_a_v2_message_id_wins_and_the_resolver_is_not_asked(mailbox, resolver):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, headers=[f"References: {V1_ID}"]))
    collect()
    inbound_message = only_inbound()
    assert inbound_message.approved_message_id == message.pk and resolver.CALLS == []


def test_bgl6_the_resolver_is_fixed_in_code_and_names_only_the_first_generation_app():
    def problems(path, environment="test", installed=("correspondence",), environ=None):
        settings = SimpleNamespace(CATALYST_FOREIGN_THREAD_RESOLVER=path, CATALYST_ENV=environment,
                                   INSTALLED_APPS=list(installed))
        return guards.dispatch_problems(settings, environ or {})

    assert problems("") == [] and problems("tests.foreign_threads_fake") == []
    assert problems("firstgen.threads", "production", ("correspondence", "firstgen")) == []
    for path, environment, installed in (("firstgen.threads", "production", ("correspondence",)),
                                         ("tests.foreign_threads_fake", "production", ("correspondence",)),
                                         ("correspondence.association", "test", ("correspondence",))):
        assert any("CATALYST_FOREIGN_THREAD_RESOLVER must be empty" in p for p in problems(path, environment, installed))
    assert any("CATALYST_FOREIGN_THREAD_RESOLVER may not be set from the environment" in p
               for p in problems("", environ={"CATALYST_FOREIGN_THREAD_RESOLVER": "x"}))


# --- the cursor at the swap ----------------------------------------------------------------------------------------

@pytest.fixture
def unset(ready, tls, settings):  # noqa: F811
    """`mailbox` without the bootstrap: the IMAP server and settings, no cursor."""
    imap = ScriptedIMAP(tls=tls.good).start()
    settings.CATALYST_MAIL_CA_FILE = tls.ca
    settings.CATALYST_MAIL_IMAP_PORT = imap.port
    settings.CATALYST_MAIL_TRUSTED_AUTHSERV_ID = TRUSTED
    settings.CATALYST_MAIL_MAILBOX_REF, settings.CATALYST_MAIL_COLLECT_FOLDER = "applicants", "INBOX"
    settings.CATALYST_MAIL_SENT_FOLDER = ""
    settings.CATALYST_MAIL_POLL_SECONDS = 3600
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    ready.imap = imap
    yield ready
    imap.stop()


def start(*args):
    out = StringIO()
    call_command("catalyst_mail_cursor_start", *args, stdout=out)
    return out.getvalue()


def the_cursor():
    return MailboxCursor.objects.get(mailbox_ref="applicants", folder="INBOX")


def test_bgl6_the_cursor_starts_where_the_first_generation_stopped_and_nothing_earlier_is_read(unset):
    validity = unset.imap.folders["INBOX"].uidvalidity
    for n in range(3):  # what the first generation already read
        unset.imap.deliver(reply(None, in_reply_to=False, body=f"earlier {n}"))
    first_new = unset.imap.deliver(reply(None, in_reply_to=False, body="after the swap"))
    logins = unset.imap.logins
    output = start("--from-uid", str(first_new), "--uidvalidity", str(validity))
    assert unset.imap.logins == logins  # the command never logs in
    cursor = the_cursor()
    assert (cursor.start_mode, cursor.uidvalidity, cursor.last_uid) == ("takeover", validity, first_new - 1)
    assert f"from_uid={first_new}" in output and "@" not in output
    assert StaffItem.objects.filter(reason_code="mailbox_history_out_of_scope").count() == 1
    collect()
    assert list(InboundMessageLocation.objects.values_list("uid", flat=True)) == [first_new]
    cursor = the_cursor()
    assert cursor.state == "ok" and cursor.complete_through_at is not None and cursor.last_uid == first_new


def test_bgl6_a_set_cursor_is_moved_only_with_the_override_and_never_back_over_collected_mail(unset):
    validity = unset.imap.folders["INBOX"].uidvalidity
    start("--from-uid", "1", "--uidvalidity", str(validity))
    unset.imap.deliver(reply(None, in_reply_to=False))
    collect()
    with pytest.raises(CommandError, match="cursor_already_set_use_override"):
        start("--from-uid", "5", "--uidvalidity", str(validity))
    with pytest.raises(CommandError, match="locations_known_at_or_after_from_uid_use_recover"):
        start("--from-uid", "1", "--uidvalidity", str(validity), "--override")
    epoch = the_cursor().epoch
    start("--from-uid", "5", "--uidvalidity", str(validity), "--override")
    cursor = the_cursor()
    assert (cursor.epoch, cursor.last_uid, cursor.start_mode, cursor.complete_through_at) == (epoch + 1, 4, "takeover", None)
    for bad in (("0", "1"), ("1", "0"), ("-3", "1")):
        with pytest.raises(CommandError, match="must_be_positive"):
            start("--from-uid", bad[0], "--uidvalidity", bad[1], "--override")


def test_bgl6_a_wrong_uidvalidity_blocks_instead_of_reprocessing_the_inbox(unset):
    validity = unset.imap.folders["INBOX"].uidvalidity
    for _ in range(3):
        unset.imap.deliver(reply(None, in_reply_to=False))
    start("--from-uid", "3", "--uidvalidity", str(validity + 7))
    collect()
    cursor = the_cursor()
    assert (cursor.state, cursor.blocked_reason) == ("blocked", inbound.TAKEOVER_VALIDITY)
    assert InboundMessage.objects.count() == 0 and cursor.last_uid == 2
    assert StaffItem.objects.filter(reason_code="collector_blocked", status="open").count() == 1
    start("--from-uid", "3", "--uidvalidity", str(validity), "--override")  # the operator corrects it
    collect()
    assert list(InboundMessageLocation.objects.values_list("uid", flat=True)) == [3]


def test_bgl6_under_the_swap_a_cursor_the_command_did_not_set_never_reads(mailbox, settings):
    """The bootstrapped cursor stands for v2's own mailbox: under the swap value it would meet the first generation's
    UIDVALIDITY and resynchronize from UID 1. It blocks instead, until the operator sets the cursor."""
    settings.CATALYST_MAIL_TAKEOVER = guards.MAIL_TAKEOVER_VALUE
    mailbox.imap.deliver(reply(None, in_reply_to=False))
    collect()
    cursor = MailboxCursor.objects.get(pk=mailbox.cursor.pk)
    assert (cursor.state, cursor.blocked_reason) == ("blocked", inbound.TAKEOVER_NOT_STARTED)
    assert InboundMessage.objects.count() == 0
    validity = mailbox.imap.folders["INBOX"].uidvalidity
    start("--from-uid", "1", "--uidvalidity", str(validity), "--override")
    collect()
    assert InboundMessage.objects.count() == 1 and MailboxCursor.objects.get(pk=mailbox.cursor.pk).state == "ok"
