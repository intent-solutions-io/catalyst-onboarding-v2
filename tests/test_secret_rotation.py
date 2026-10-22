"""6B.10a (027; 026 section 5, P6-D-15; TEST-P6-21 to 24): each secret class's rotation does what the runbook says.
The webhook secrets' two-secret overlap is tested in test_agreement_completion (a rotation: both valid)."""

import os
import re
import sys
from urllib.parse import urlencode

from django.core import mail
from django.test import Client

from config.post_restore import ITEMS
from correspondence.models import StaffItem
from tests import support
from tests.support import manage_as_owner
from tests.test_outbound import FORM, VALID, p2, run_worker, staff  # noqa: F401  (fixture chain and helpers)

OLD_KEY = "synthetic-old-link-key-" + "Qw3Er5Ty7Ui9Op1As3Df5Gh7Jk9Lz2X" * 2  # gitleaks:allow
NEW_KEY = "synthetic-new-link-key-" + "Mn8Bv6Cx4Za2Sd0Fg8Hj6Kl4Qw2Er0T" * 2  # gitleaks:allow


def confirmation_link(settings, email="rotation@example.test") -> str:
    settings.CATALYST_VERIFICATION_KEY, settings.CATALYST_VERIFICATION_FALLBACK_KEYS = OLD_KEY, []
    response = Client().post(FORM, urlencode({**VALID, "email": email}), content_type="application/x-www-form-urlencoded")
    assert response.status_code == 302
    run_worker()
    return re.search(r"http://catalyst\.example\.test(/confirm/\S+/)", mail.outbox[-1].body).group(1)


def offered(path) -> bool:
    return b'name="version"' in Client().get(path).content


def test_6b10a_a_routine_link_key_rotation_keeps_links_in_hand_working_while_the_old_key_is_a_fallback(p2, settings):
    path = confirmation_link(settings)
    assert offered(path)  # before: signed and checked with the old key
    settings.CATALYST_VERIFICATION_KEY, settings.CATALYST_VERIFICATION_FALLBACK_KEYS = NEW_KEY, [OLD_KEY]
    assert offered(path)  # step 1: the new key signs, the old one still verifies the links already sent
    settings.CATALYST_VERIFICATION_FALLBACK_KEYS = []
    assert not offered(path)  # step 2, after the longest link lifetime: the old key is gone and so are its links


def test_6b10a_after_a_leak_the_old_links_fail_and_every_outstanding_one_is_closed_for_reissue(p2, settings):
    path = confirmation_link(settings, "leaked@example.test")
    settings.CATALYST_VERIFICATION_KEY, settings.CATALYST_VERIFICATION_FALLBACK_KEYS = NEW_KEY, []  # no fallback
    assert not offered(path)  # links signed with the leaked key fail at once
    report = manage_as_owner("catalyst_close_links", "--confirm-database", support_db()).stdout
    assert '"confirmation_links_closed": 1' in report
    assert StaffItem.objects.filter(reason_code=ITEMS["rotation"][0], status="open").count() == 1  # staff reissue
    settings.CATALYST_VERIFICATION_KEY = OLD_KEY
    assert not offered(path)  # closed, not just unverifiable: even the leaked key no longer opens it


def test_6b10a_closing_links_refuses_while_a_fallback_key_remains_or_for_another_database(p2):
    from django.conf import settings

    base = [sys.executable, "manage.py", "catalyst_close_links", "--confirm-database"]
    owner = {"CATALYST_DB_NAME": support_db(), "CATALYST_DB_USER": settings.CATALYST_DB_ROLES["owner"],
             "CATALYST_DB_PASSWORD": os.environ["CATALYST_DB_OWNER_PASSWORD"]}
    wrong = support.run([*base, "another-database"], **owner)
    assert wrong.returncode == 1 and "must name this database" in wrong.stderr
    fallback = support.run([*base, support_db()], **owner, CATALYST_VERIFICATION_FALLBACK_KEYS=OLD_KEY)
    assert fallback.returncode == 1 and "must not stay a fallback" in fallback.stderr


def test_6b10a_rotating_the_django_secret_key_ends_every_staff_session(p2, settings):
    staff(p2, "rotation-staff", superuser=True)
    client = Client()
    assert client.login(username="rotation-staff", password="synthetic-password-only")  # gitleaks:allow
    assert client.get("/staff/").status_code == 200
    settings.SECRET_KEY = "synthetic-rotated-django-key-" + "Zx9Cv7Bn5Mq3Wr1Ty8Ui6Op4As2Df0" * 2  # gitleaks:allow
    response = client.get("/staff/")
    assert response.status_code == 302 and response["Location"].startswith("/staff/login/")  # sign in again


def test_6b10a_a_rotated_role_password_takes_effect_and_the_old_one_stops_working(p2):
    import psycopg
    from django.conf import settings
    from django.db import connection

    script = [sys.executable, "scripts/provision_db_roles.py"]
    admin = {"CATALYST_DB_ADMIN_USER": os.environ["CATALYST_DB_ADMIN_USER"],
             "CATALYST_DB_ADMIN_PASSWORD": os.environ["CATALYST_DB_ADMIN_PASSWORD"], "CATALYST_ENV": "test"}
    old, new = os.environ["CATALYST_DB_RETENTION_PASSWORD"], "synthetic-rotated-retention-" + "Kp4Lm6Nb8Vc0" * 3

    def login(password):
        return psycopg.connect(host=connection.settings_dict["HOST"], port=connection.settings_dict["PORT"],
                               dbname=connection.settings_dict["NAME"], user=settings.CATALYST_DB_ROLES["retention"],
                               password=password, connect_timeout=5)
    try:
        assert support.run(script, **admin, CATALYST_DB_RETENTION_PASSWORD=new).returncode == 0
        login(new).close()
        try:
            login(old).close()
            raise AssertionError("the old password still works")
        except psycopg.OperationalError:
            pass
    finally:  # back to this run's own password, whatever happened
        assert support.run(script, **admin).returncode == 0
    login(old).close()


def support_db() -> str:
    from django.db import connection

    return connection.settings_dict["NAME"]
