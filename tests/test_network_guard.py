"""The Python-level test network guard (TEST-S1-14; limits in conftest.py): inside a test function, Python
socket connections beyond loopback and the database host fail."""

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


def test_connect_ex_keeps_its_errno_semantics_for_allowed_hosts():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]  # bound but not listening: connections are refused
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            assert s.connect_ex(("127.0.0.1", closed_port)) != 0


def test_connect_ex_to_an_external_address_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(RuntimeError, match="network access blocked"):
            s.connect_ex(("192.0.2.10", 443))
