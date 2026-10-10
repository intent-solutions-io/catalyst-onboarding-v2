"""The test-wide network guard (TEST-S1-14): outbound connections beyond loopback and the database fail."""

import socket

import pytest


def test_connection_to_an_external_address_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        with pytest.raises(RuntimeError, match="network access blocked"):
            s.connect(("192.0.2.10", 443))  # TEST-NET-1, never routable


def test_an_smtp_send_cannot_leave_the_test_process(settings):
    from django.core.mail import send_mail

    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST, settings.EMAIL_PORT, settings.EMAIL_TIMEOUT = "192.0.2.10", 587, 1
    with pytest.raises(RuntimeError, match="network access blocked"):
        send_mail("synthetic", "synthetic body", "noreply@example.test", ["applicant@example.test"])


@pytest.mark.django_db
def test_database_access_is_unaffected_by_the_guard():
    # libpq connects outside Python sockets; this only shows the guard does not break the database.
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("select 1")
        assert cursor.fetchone() == (1,)
