"""9kg.75: the read-only report of who is due for erasure under the retention clocks (031 section 2.5; 033 Q1).

Synthetic people only. The clocks are a year and three months long, so the tests move the evaluation date forward with
`--as-of` rather than backdating protected history: each rule lists a person exactly once their clock has run out and
not the day before. The report runs only as the retention login and prints references and counts, never an address.
"""

import json
import sys
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from erasure import registry
from tests.support import manage_as_owner, run
from tests.test_erasure import subject
from tests.test_erasure_lookup import _env, as_retention
from tests.test_intake_notice import LABEL_A, on_file
from tests.test_invitation import ensure_notice_templates

INVITED = "never.applied@example.test"


def report(on: date) -> dict:
    done = as_retention("catalyst_retention_due", "--as-of", on.isoformat())
    assert done.returncode == 0, done.stderr
    for address in ("example.test", "@"):
        assert address not in done.stdout  # references and counts only
    return json.loads(done.stdout)


def test_9kg_75_each_rule_lists_a_person_exactly_when_the_clock_has_run_out(privileged_reset):
    ended = subject("ended.r1@example.test", "Ended Example", stage="withdrawn")
    subject("still.open@example.test", "Open Example", stage="awaiting_decision")
    member = subject("member.r3@example.test", "Member Example", stage="withdrawn")
    on_file(member.email_key, "--nda", LABEL_A)
    ensure_notice_templates()
    invited = json.loads(manage_as_owner("catalyst_invite", INVITED, "--issued-by", "owner probe", "--days", "1").stdout)
    today = date.today()

    first = report(today + timedelta(days=90))  # the invitation expired a day after issue: R2 needs 90 more days
    assert first["due"] == {"R1": [], "R2": []}
    assert first["counts"] == {"R1": 0, "R2": 0, "R3_not_computable": 1, "open": 1}
    assert first["provisional"] is True and first["clock_days"] == registry.CLOCK_DAYS  # the shipped values (9kg.84)
    assert set(first["not_computable"]) == {"R3", "R4"}

    second = report(today + timedelta(days=92))
    assert second["due"] == {"R1": [], "R2": [invited["invitation"]]}

    third = report(today + timedelta(days=364))  # R1: a year after the terminal event, not a day before
    assert third["due"]["R1"] == []
    fourth = report(today + timedelta(days=367))
    assert fourth["due"] == {"R1": [str(ended.public_ref)], "R2": [invited["invitation"]]}
    assert fourth["counts"]["open"] == 1 and fourth["counts"]["R3_not_computable"] == 1  # never listed as due


def test_9kg_75_the_report_refuses_another_login_a_web_or_worker_process_and_an_undecided_registry(
        privileged_reset, monkeypatch):
    for role in ("owner", "app"):
        refused = run([sys.executable, "manage.py", "catalyst_retention_due"], **_env(role))
        assert refused.returncode == 1 and "not_the_retention_role" in refused.stderr, (role, refused.stderr)
    from config import runtime

    runtime.declare_process("worker")
    try:
        with pytest.raises(CommandError, match="not_a_management_process"):
            call_command("catalyst_retention_due")
    finally:
        runtime.declare_process("management")
    monkeypatch.setattr(registry, "REGISTRY", {name: {"treatment": "undecided", "retention": "undecided"}
                                               for name in registry.REGISTRY})
    with pytest.raises(CommandError, match="registry_undecided"):
        call_command("catalyst_retention_due")
