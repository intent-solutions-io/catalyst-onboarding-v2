"""9kg.77: production's Django mailer sends the three link mails through `correspondence.transport` (config.mail).

The contact confirmation, the password setup and the withdrawal link are sent by Django's mailer. In production its
backend is `config.mail.TransportEmailBackend`, so they leave through the one SMTP path with its host allow-list, its
pinned login, verified TLS and its process-kind rule, and every outcome but `accepted_by_server` raises so each sender
takes its failure path. The loopback scripted server stands in for the mail host (016 A3).
"""

import email

import pytest
from django.core.mail import EmailMessage, get_connection

from config import guards, mail
from tests.smtp_server import ScriptedSMTP
from tests.test_outbound import p2  # noqa: F401  (fixture chain: the loopback transport settings)


def message(connection, **overrides):
    fields = dict(subject="Confirm your address", body="Open https://catalyst-v2.example.test/confirm/synthetic/",
                  from_email="onboarding@catalyst-v2.example.test", to=["ada@example.test"])
    return EmailMessage(**{**fields, **overrides}, connection=connection)


def test_9kg_77_a_message_leaves_through_the_transport_with_crlf_and_one_recipient(p2):
    connection = get_connection(guards.TRANSPORT_EMAIL_BACKEND)
    assert message(connection).send(fail_silently=False) == 1
    [sent] = p2.server.messages
    assert sent["rcpts"] == ["ada@example.test"] and "onboarding@catalyst-v2.example.test" in sent["from"]
    assert b"\r\n" in sent["data"] and b"\n" not in sent["data"].replace(b"\r\n", b"")  # SMTP line ends only
    parsed = email.message_from_bytes(sent["data"])
    assert parsed["Subject"] == "Confirm your address" and parsed["Message-ID"] and parsed["Date"]


@pytest.mark.parametrize(("script", "error"), [
    ({"rcpt": 550}, mail.MailRefused), ({"rcpt": 450}, mail.MailRefused), ({"greeting": 421}, mail.MailRefused),
    ({"end": "drop"}, mail.MailUncertain), ({"end": 554}, mail.MailRefused),
])
def test_9kg_77_anything_but_acceptance_raises_so_the_sender_takes_its_failure_path(p2, script, error):
    p2.use(ScriptedSMTP(script))
    with pytest.raises(error) as raised:
        message(get_connection(guards.TRANSPORT_EMAIL_BACKEND)).send(fail_silently=False)
    assert "@" not in str(raised.value)  # an outcome and a phase, never an address
    if error is mail.MailUncertain:
        assert str(raised.value).startswith("unknown:")


def test_9kg_77_one_recipient_only_and_nothing_sent_otherwise(p2):
    connection = get_connection(guards.TRANSPORT_EMAIL_BACKEND)
    for overrides in ({"to": ["a@example.test", "b@example.test"]}, {"cc": ["c@example.test"]},
                      {"bcc": ["d@example.test"]}):
        with pytest.raises(mail.MailRefused, match="one_recipient_only"):
            message(connection, **overrides).send(fail_silently=False)
    # No recipient: Django returns 0 before any backend runs, and every sender treats a count other than 1 as a failure.
    assert message(connection, to=[]).send(fail_silently=False) == 0
    assert p2.server.messages == [] and p2.server.connections == 0


def test_9kg_77_no_mail_host_means_no_send(p2, settings):
    settings.CATALYST_MAIL_HOST = ""  # the dark deploy: no mail host configured
    with pytest.raises(mail.MailRefused, match="transport_blocked"):
        message(get_connection(guards.TRANSPORT_EMAIL_BACKEND)).send(fail_silently=False)
    assert p2.server.messages == []


def test_9kg_77_the_transport_backend_is_admitted_only_in_a_live_environment():
    for environment in ("test", "development", "staging"):
        assert guards.provider_problems(guards.TRANSPORT_EMAIL_BACKEND, {}, environment), environment
    assert guards.provider_problems(guards.TRANSPORT_EMAIL_BACKEND, {}, "production") == []
    # Django's own SMTP backend never: it bypasses the allow-list, the pin and the peer check.
    assert guards.provider_problems("django.core.mail.backends.smtp.EmailBackend", {}, "production")
