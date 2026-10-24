"""6B.10a (027; 026 section 5, P6-D-15; TEST-P6-21 to 24): each secret class's rotation does what the runbook says.
The webhook secrets' two-secret overlap is tested in test_agreement_completion (a rotation: both valid)."""

import hashlib
import json
import os
import re
import sys
from urllib.parse import urlencode

from django.core import mail
from django.test import Client

from config.post_restore import ITEMS
from correspondence.models import StaffItem
from tests import support
from tests.test_closure import cl  # noqa: F401  (fixture chain)
from tests.test_credentials import invited
from tests.test_outbound import FORM, VALID, staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, approve, c, d, ev, g, h, issued, k, nda, p2, pv, run_worker, sign_and_settle, tls,
)

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


def leaked_digest(key=OLD_KEY) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def close_links(**env):
    from django.conf import settings

    return support.run([sys.executable, "manage.py", "catalyst_close_links", "--confirm-database", support_db(),
                        "--leaked-key-sha256", leaked_digest()], CATALYST_DB_NAME=support_db(),
                       CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                       CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"], **env)


def test_6b10a_after_a_leak_the_old_links_fail_and_every_outstanding_one_is_closed_for_reissue(p2, settings):
    path = confirmation_link(settings, "leaked@example.test")
    assert offered(path)  # before: the link works under the key about to leak
    settings.CATALYST_VERIFICATION_KEY, settings.CATALYST_VERIFICATION_FALLBACK_KEYS = NEW_KEY, []  # no fallback
    assert not offered(path)  # links signed with the leaked key fail at once
    result = close_links(CATALYST_VERIFICATION_KEY=NEW_KEY)  # the command runs with the new key deployed
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"confirmation_links_closed": 1}  # nothing else
    item = StaffItem.objects.get(reason_code=ITEMS["rotation"][0], status="open")  # staff reissue
    assert item.dedupe_key.startswith("rotation:confirmation:")
    settings.CATALYST_VERIFICATION_KEY = OLD_KEY
    assert not offered(path)  # closed, not just unverifiable: even the leaked key no longer opens it


def test_6b10a_closing_links_refuses_while_the_leaked_key_is_still_the_link_key(p2, settings):
    path = confirmation_link(settings, "early@example.test")
    result = close_links(CATALYST_VERIFICATION_KEY=OLD_KEY)  # run before the new key was deployed
    assert result.returncode == 1 and "still the link key" in result.stderr
    assert offered(path)  # nothing was closed
    bad = support.run([sys.executable, "manage.py", "catalyst_close_links", "--confirm-database", support_db(),
                       "--leaked-key-sha256", "not-a-digest"], **owner_env())
    assert bad.returncode == 1 and "64 lowercase hex" in bad.stderr


def test_6b10a_password_links_are_not_signed_with_the_link_key_and_survive_its_rotation(cl, monkeypatch, settings):
    from provisioning.models import CredentialSetup

    app, request, setup_path = invited(cl, monkeypatch)
    assert Client().get(setup_path).status_code == 200  # before
    settings.CATALYST_VERIFICATION_KEY, settings.CATALYST_VERIFICATION_FALLBACK_KEYS = NEW_KEY, []
    assert Client().get(setup_path).status_code == 200  # a random token, unaffected by the key
    result = close_links(CATALYST_VERIFICATION_KEY=NEW_KEY)
    assert result.returncode == 0, result.stderr
    assert Client().get(setup_path).status_code == 200  # and the leak procedure leaves it alone
    assert CredentialSetup.objects.get(request=request).state not in ("superseded", "set_uncertain")


def owner_env() -> dict:
    from django.conf import settings

    return {"CATALYST_DB_NAME": support_db(), "CATALYST_DB_USER": settings.CATALYST_DB_ROLES["owner"],
            "CATALYST_DB_PASSWORD": os.environ["CATALYST_DB_OWNER_PASSWORD"]}


def test_6b10a_closing_links_refuses_while_a_fallback_key_remains_or_for_another_database(p2):
    base = [sys.executable, "manage.py", "catalyst_close_links", "--leaked-key-sha256", leaked_digest(),
            "--confirm-database"]
    wrong = support.run([*base, "another-database"], **owner_env(), CATALYST_VERIFICATION_KEY=NEW_KEY)
    assert wrong.returncode == 1 and "must name this database" in wrong.stderr
    fallback = support.run([*base, support_db()], **owner_env(), CATALYST_VERIFICATION_KEY=NEW_KEY,
                           CATALYST_VERIFICATION_FALLBACK_KEYS=OLD_KEY)
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
    admin = {**support.superuser_probe(), "CATALYST_ENV": "test"}  # this test acts as the administrator (6hl.10)
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
