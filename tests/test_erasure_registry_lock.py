"""9kg.84: the provisional POL-10 values and the intake lock they carry (council record 033 Q1 and Q2(a), D-52).

The shipped registry is filled with 031 section 2 as amended by 033 Q1, so a live backup and an erasure of the dark
deploy's synthetic subjects are possible. While `PROVISIONAL` is set, a live environment takes no real intake: the
request form is withheld, `catalyst_invite` issues nothing, and health reports it. The suite runs with the lock lifted
(tests/conftest.py); these tests set it back.
"""

import importlib.util
import logging

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from applications import notices, views
from applications.models import Invitation
from config import backup, system_health
from erasure import registry
from erasure import service
from tests.test_erasure import KEY, Crash, decided, erase, subject  # noqa: F401  (fixture)
from tests.test_intake import FORM, counts, post
from tests.test_intake_notice import approve_notice, closed, real_version
from tests.test_invitation import ADA
from tests.test_system_health import health


def shipped_registry():
    """The module as shipped, loaded afresh: the suite's fixture lifts the lock on the imported one."""
    spec = importlib.util.spec_from_file_location("shipped_erasure_registry", registry.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_9kg_84_the_registry_ships_filled_with_the_provisional_values_and_locked():
    shipped = shipped_registry()
    assert shipped.PROVISIONAL is False  # D-53: cleared by the owner's go; the lock itself is tested below
    assert shipped.problems() == []  # decided: an erasure and a live backup are no longer refused by the registry
    rows = shipped.REGISTRY
    assert all(rows[name]["treatment"] == shipped.ANONYMIZE for name in shipped.SUBJECT_CLASSES)
    assert rows["signed_documents"]["treatment"] == shipped.DESTROY_KEY
    assert rows["provider_copies"]["treatment"] == shipped.MANUAL_HANDOFF
    assert rows["erasure_record"]["treatment"] == rows["effect_journal"]["treatment"] == shipped.RETAIN
    clock = rows["application_identity"]["retention"]
    assert "R1 P12M" in clock and "R2 P3M" in clock and "R4 P30D from receipt" in clock
    assert "engagement end, period COUNSEL" in clock  # R3 is counsel's: the reason the values stay provisional
    assert "P30D from receipt" in rows["provider_copies"]["retention"]
    assert "COUNSEL" in rows["erasure_record"]["retention"]  # the keyed hash's lifetime


def test_9kg_84_while_provisional_a_live_environment_takes_no_intake_and_issues_no_invitation(
        privileged_reset, settings, monkeypatch, caplog):
    monkeypatch.setattr(views, "_withheld_logged", {})
    monkeypatch.setattr(notices, "verification_withheld", lambda: False)  # 9kg.80 has its own tests
    closed(settings)
    owner = approve_notice(privileged_reset, notices.DATA_NOTICE)
    real_version(privileged_reset, notices.DATA_NOTICE, 2, "Real wording, approved by the owner.\n", owner)
    settings.CATALYST_ENV = "production"
    monkeypatch.setattr(registry, "PROVISIONAL", True)
    caplog.set_level(logging.WARNING, logger="applications.views")
    before = counts()
    client = Client()
    assert client.get(FORM).status_code == 503
    assert post(client, email=ADA).status_code == 503 and counts() == before
    assert "intake page withheld: registry_provisional" in caplog.text
    with pytest.raises(CommandError, match=r"refused \(registry_provisional\)"):
        call_command("catalyst_invite", ADA, "--issued-by", "owner probe")
    assert Invitation.objects.count() == 0
    code, report = health()
    assert code == 1 and report["intake"]["registry_provisional"] is True
    assert "registry_provisional" in report["intake"]["anomalies"]
    # The dark deploy can be backed up: the filled registry no longer refuses a live backup.
    backup.refuse_real_backup_while_undecided()
    assert system_health.backup_health()["anomalies"] == []
    # A synthetic environment is not locked.
    settings.CATALYST_ENV = "test"
    assert client.get(FORM).status_code == 200 and not registry.intake_locked()
    # Lifted (counsel's values, a later release): the approved real notice is served in the live environment again,
    # and the invitation is refused only for its own wording, never for the lock.
    settings.CATALYST_ENV = "production"
    monkeypatch.setattr(registry, "PROVISIONAL", False)
    assert client.get(FORM).status_code == 200
    with pytest.raises(CommandError) as refused:
        call_command("catalyst_invite", ADA, "--issued-by", "owner probe")
    assert "registry_provisional" not in str(refused.value)
    assert health()[1]["intake"]["registry_provisional"] is False


def test_9kg_84_the_shipped_values_finish_an_interrupted_erasure_with_nothing_in_custody(privileged_reset, decided, monkeypatch):
    """CodeRabbit on PR #129: under the shipped `destroy_key`, a resumed erasure required the custody key store even with
    nothing in custody. In wave 1 no key directory is configured, so the dark deploy's subjects could not be finished."""
    from applications.models import Application

    monkeypatch.setattr(registry, "REGISTRY", shipped_registry().REGISTRY)
    assert registry.REGISTRY["signed_documents"]["treatment"] == registry.DESTROY_KEY
    one = subject("dark-deploy@example.test", "Synthetic Subject")
    real_call = service._call

    def crash_before_commit(conn, *args, commit):
        if commit:
            raise Crash("the operator's terminal closed")
        return real_call(conn, *args, commit=commit)
    monkeypatch.setattr(service, "_call", crash_before_commit)
    with pytest.raises(Crash):
        erase(privileged_reset, one.public_ref)
    monkeypatch.setattr(service, "_call", real_call)
    resumed = erase(privileged_reset, one.public_ref)  # no key directory is configured here
    assert resumed.status == "erased" and resumed.resumed
    assert Application.objects.get(pk=one.pk).email == "[erased]"
