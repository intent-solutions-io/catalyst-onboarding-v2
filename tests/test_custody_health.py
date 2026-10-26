"""9kg.70: the custody key store's state is a health part (config.system_health.custody_health) that pages each
fault under its own code, counts only, without the wrapping key; an erased document's absent key is counted, never
paged (release-ops review of PR #102). Every key and document here is synthetic.
"""

import json
import re

import pytest

from agreements import keystore
from agreements.management.commands import catalyst_custody_drill as drill
from config import system_health
from tests.test_custody_encryption import custody  # noqa: F401  (fixture)
from tests.test_erasure import subject
from workflow import journal


def stored(i=0, sealed=True):
    app = subject(email=f"health-{i}@example.test", name=f"Health Example {i}")
    return drill.synthetic_document(app, f"%PDF-1.7 synthetic health {i}".encode(), sealed=sealed)


@pytest.mark.django_db
def test_9kg_70_a_healthy_store_raises_nothing_and_an_erased_document_is_counted_never_paged(custody, settings):
    kept, erased = stored(0), stored(1)
    keystore.destroy(str(erased.application.public_ref), [erased.envelope.key_ref])
    settings.CATALYST_CUSTODY_WRAPPING_KEY = ""  # the part needs no wrapping key
    part = system_health.custody_health()
    assert part["anomalies"] == [], part
    assert (part["documents"], part["sealed"], part["erased_documents"], part["keys_primary"]) == (2, 2, 1, 1)
    text = json.dumps(part)
    assert kept.envelope.key_ref not in text and str(custody) not in text and "@" not in text  # counts only


@pytest.mark.django_db
@pytest.mark.parametrize("fault, code", [
    ("mirror_lost", "recovery_incomplete"), ("primary_lost", "recovery_incomplete"), ("both_lost", "key_lost"),
    ("destroyed_back", "destroyed_still_present"), ("unsealed", "in_the_clear"), ("orphan_key", "orphans"),
    ("garbage", "key_invalid"), ("stray", "key_invalid"), ("rotation_begun", "rotation_incomplete"),
    ("no_marker", "key_store_unavailable"),
])
def test_9kg_70_each_fault_pages_under_its_own_code(custody, settings, fault, code):
    document = stored(0)
    ref = document.envelope.key_ref
    primary, mirror = keystore.directories()
    if fault == "mirror_lost":
        keystore._unlink(mirror, ref)
    elif fault == "primary_lost":
        keystore._unlink(primary, ref)
    elif fault == "both_lost":
        keystore._unlink(mirror, ref), keystore._unlink(primary, ref)
    elif fault == "destroyed_back":
        blob = keystore._read(primary, ref)
        keystore.destroy(str(document.application.public_ref), [ref])
        keystore._write(primary, ref, blob)  # a copied or restored key file outlives its destruction
    elif fault == "unsealed":
        stored(1, sealed=False)
    elif fault == "orphan_key":
        keystore.create()  # a write whose record never came
    elif fault == "garbage":
        keystore._write(primary, "f" * 32, b"not a wrapped key")
        keystore._write(mirror, "f" * 32, b"not a wrapped key")
    elif fault == "stray":
        (primary / f"{ref}.key.rotating").write_bytes(b"left by an interrupted rotation")
        (primary / f"{ref}.key.rotating").chmod(0o600)
    elif fault == "rotation_begun":
        journal.append("custody_rotation", "custody_rotation:" + "1" * 16 + ":" + "2" * 16,
                       {"from_key": "1" * 16, "to_key": "2" * 16, "phase": "prepare"})
    elif fault == "no_marker":
        (mirror / keystore.MARKER).unlink()  # an unmounted volume: never read as an empty store
    part = system_health.custody_health()
    assert code in part["anomalies"], part
    if fault != "garbage":  # an unreadable key file is also a key no record names (`orphans`)
        assert part["anomalies"] == [code], part  # its own code, not a cascade


@pytest.mark.django_db
def test_9kg_70_keys_under_two_wrapping_keys_are_an_unfinished_rotation(custody, settings):
    import secrets

    first, second = stored(0), stored(1)
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    old = keystore.wrapping_key()
    primary, mirror = keystore.directories()
    ref = second.envelope.key_ref
    rewrapped = keystore._wrap(keystore.next_wrapping_key(), ref, keystore._unwrap(old, ref, keystore._read(primary, ref)))
    keystore._replace(primary, ref, rewrapped)  # as a rotation interrupted after one file
    keystore._replace(mirror, ref, rewrapped)
    assert system_health.custody_health()["anomalies"] == ["rotation_incomplete"]
    assert first.envelope.key_ref != ref


def test_9kg_70_an_unconfigured_store_reports_nothing(settings):
    settings.CATALYST_CUSTODY_KEY_DIR = settings.CATALYST_CUSTODY_KEY_MIRROR_DIR = ""
    assert system_health.custody_health() == {"configured": False, "anomalies": []}


@pytest.mark.django_db
def test_9kg_70_the_health_command_names_the_custody_code_and_exits_1(custody, settings):
    document = stored(0)
    primary, mirror = keystore.directories()
    keystore._unlink(mirror, document.envelope.key_ref), keystore._unlink(primary, document.envelope.key_ref)
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    with pytest.raises(SystemExit) as exited:
        call_command("catalyst_health", stdout=out)
    assert exited.value.code == 1
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert "custody.key_lost" in report["anomalies"]
    assert all(re.fullmatch(r"[a-z_]+\.[a-z_]+", a) for a in report["anomalies"])  # health.sh's rule for a code
