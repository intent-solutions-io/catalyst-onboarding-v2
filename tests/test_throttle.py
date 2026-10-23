"""9kg.29 (029 section 4.1; REQ-027): the public endpoints' limits and the client identity they key on.

Every request runs as the application role (tests/conftest.py). The suite opens every limit per test (conftest
SUITE_PUBLIC_ENTRY); each test here sets the limits it proves. Tests that age a window through the owner, or that
commit, use `privileged_reset`; the others roll back.
"""

import json
import logging
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from django.db import DatabaseError, connection
from django.db.models.functions import Now
from django.test import Client, RequestFactory

from accounts import staff_access
from accounts.models import RequestThrottle
from applications.models import Application
from config import client_identity, guards, throttle
from tests.test_confirmation import intake, link_for, path_of, post_confirm, version
from tests.test_intake import EMPTY, FORM, RECEIVED, VALID, counts, post
from workflow import ledger

HOOK = "/hooks/documenso/"
PROXY_CLIENT, OTHER_CLIENT, THIRD_CLIENT = "203.0.113.5", "198.51.100.7", "192.0.2.9"  # documentation ranges


def post_from(client, forwarded, **fields):
    """A form POST carrying a forwarded-address header, as the proxy would (or a client pretending to be it)."""
    return client.post(FORM, urlencode({**VALID, **fields}), content_type="application/x-www-form-urlencoded",
                       HTTP_X_FORWARDED_FOR=forwarded)


def refusal_shape(response):
    """What the applicant can compare across endpoints: the status and the page. (Cache headers differ by path: the
    token paths add never_cache and the private-response middleware; every refusal still carries no-store.)"""
    assert "no-store" in response["Cache-Control"]
    return response.status_code, response.content


def keys_carry_no_value(*values):
    stored = list(RequestThrottle.objects.values_list("key", flat=True))
    assert stored and all(len(k) == 64 and set(k) <= set("0123456789abcdef") for k in stored)
    for value in values:
        assert all(value not in k for k in stored)


# --- the client identity (config.client_identity) --------------------------------------------------------------

@pytest.mark.parametrize(("raw", "bucket"), [
    ("203.0.113.5", "203.0.113.5"), (" 203.0.113.5 ", "203.0.113.5"),
    ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),  # one IPv6 subscriber holds a /64
    ("::ffff:203.0.113.5", "203.0.113.5"),
    ("", None), ("203.0.113.5, 198.51.100.7", None), ("203.0.113.5 198.51.100.7", None), ("not-an-address", None),
    ("203.0.113.5:443", None), ("example.test", None),
])
def test_9kg_29_the_client_identity_is_exactly_one_address_literal(raw, bucket):
    assert client_identity.bucket(raw) == bucket


def test_9kg_29_the_identity_source_is_the_proxy_header_or_the_peer_and_is_fixed_in_code(settings):
    factory = RequestFactory()
    request = factory.get("/request-access/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR=PROXY_CLIENT)
    settings.CATALYST_CLIENT_IDENTITY = "direct"
    assert client_identity.client_identity(request) == "127.0.0.1"  # the forwarded header is ignored
    settings.CATALYST_CLIENT_IDENTITY = "proxy"
    assert client_identity.client_identity(request) == PROXY_CLIENT
    assert client_identity.client_identity(factory.get("/request-access/", REMOTE_ADDR="127.0.0.1")) is None
    # The guard: never from the environment, only the two sources, and the proxy everywhere but the local environments.
    ok = SimpleNamespace(CATALYST_INTAKE_MODE="invitation", CATALYST_CLIENT_IDENTITY="proxy", CATALYST_ENV="staging")
    assert guards.intake_problems(ok, {}) == []
    assert guards.intake_problems(ok, {"CATALYST_CLIENT_IDENTITY": "proxy"}) == ["CATALYST_CLIENT_IDENTITY may not be set from the environment"]
    direct = SimpleNamespace(CATALYST_INTAKE_MODE="invitation", CATALYST_CLIENT_IDENTITY="direct", CATALYST_ENV="staging")
    assert any("must be 'proxy' outside test and development" in p for p in guards.intake_problems(direct, {}))
    for environment in ("test", "development"):
        assert guards.intake_problems(SimpleNamespace(CATALYST_INTAKE_MODE="open", CATALYST_CLIENT_IDENTITY="direct",
                                                      CATALYST_ENV=environment), {}) == []
    for bad in ("", None, "header", "Proxy"):
        assert any("must be 'proxy' or 'direct'" in p for p in guards.intake_problems(
            SimpleNamespace(CATALYST_INTAKE_MODE="open", CATALYST_CLIENT_IDENTITY=bad, CATALYST_ENV="test"), {}))


# --- one refusal for every endpoint, and the window ------------------------------------------------------------

def test_9kg_29_every_public_endpoint_refuses_a_client_burst_uniformly_and_admits_again_after_the_window(
        privileged_reset, settings, caplog):
    caplog.set_level(logging.INFO, logger="config.throttle")
    settings.CATALYST_THROTTLE_INTAKE_PER_CLIENT = 2
    settings.CATALYST_THROTTLE_LINK_PER_CLIENT = 2
    settings.CATALYST_THROTTLE_WINDOW_SECONDS = 600
    client = Client()
    assert [post(client).status_code for _ in range(2)] == [302, 302]
    refused_intake = post(client)
    link = link_for(Application.objects.get())
    assert [client.get(path_of(link)).status_code for _ in range(2)] == [200, 200]
    refused_confirm = client.get(path_of(link))
    assert [client.get("/setup/not-a-real-token/").status_code for _ in range(2)] == [404, 404]
    refused_setup = client.get("/setup/not-a-real-token/")
    assert [client.get("/withdraw/not-a-real-token/").status_code for _ in range(2)] == [404, 404]
    refused_withdraw = client.get("/withdraw/not-a-real-token/")
    shapes = {refusal_shape(r) for r in (refused_intake, refused_confirm, refused_setup, refused_withdraw)}
    assert len(shapes) == 1, "one refusal page for every endpoint and every bucket"
    status, body = shapes.pop()
    assert status == 429 and b"Too many requests" in body
    assert "Location" not in refused_intake
    assert "limit reached" in caplog.text and "ada@example.test" not in caplog.text and "not-a-real-token" not in caplog.text
    # Each refused request changed nothing: still one application, one version.
    assert counts() == {"applications": 1, "versions": 2, "events": 2, "challenges": 1, "actions": 1}
    # The window passes (aged by the owner: test setup on the authorized path). Every endpoint admits again.
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("UPDATE accounts_requestthrottle SET window_start = now() - interval '1 hour'")
    assert post(client).status_code == 302
    assert client.get(path_of(link)).status_code == 200
    assert client.get("/setup/not-a-real-token/").status_code == 404
    assert client.get("/withdraw/not-a-real-token/").status_code == 404
    # A refused request did not extend the window: each bucket now counts one in its new window.
    assert set(RequestThrottle.objects.values_list("count", flat=True)) == {1}


# --- the buckets -----------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_29_intake_is_keyed_on_the_hashed_address_and_the_address_bucket_limits_issuance_not_confirmation(settings):
    settings.CATALYST_THROTTLE_INTAKE_PER_ADDRESS = 2
    client = Client()
    assert post(client).status_code == 302
    assert post(client, email="  ADA@Example.TEST ").status_code == 302  # the same identity key (005 S1.3)
    assert post(client, email="ada@example.test").status_code == 429  # the address bucket
    assert post(client, email="bob@example.test").status_code == 302  # another address, its own bucket
    keys_carry_no_value("ada@example.test", "bob@example.test", "example.test")
    # The address holder is not locked out of the link already issued: confirmation consults no address bucket.
    app = Application.objects.get(email_key="ada@example.test")
    response = post_confirm(client, link_for(app), version(app, 1).public_id)
    assert response.status_code == 200 and b"confirmed" in response.content


@pytest.mark.django_db
def test_9kg_29_link_endpoints_are_keyed_on_the_client_and_the_token_hash_and_an_unknown_token_is_refused_alike(settings):
    settings.CATALYST_THROTTLE_LINK_PER_TOKEN = 2
    client = Client()
    first, second = intake(client), intake(client, email="bob@example.test")
    link_one, link_two = link_for(first), link_for(second)
    assert [client.get(path_of(link_one)).status_code for _ in range(2)] == [200, 200]
    known = client.get(path_of(link_one))
    assert known.status_code == 429
    assert client.get(path_of(link_two)).status_code == 200  # another token, its own bucket
    assert [client.get("/confirm/no-such-token/").status_code for _ in range(2)] == [404, 404]
    unknown = client.get("/confirm/no-such-token/")
    assert refusal_shape(unknown) == refusal_shape(known)  # a token's existence cannot be read from the refusal
    keys_carry_no_value("no-such-token", path_of(link_one).split("/")[2])
    # Unchanged by the refusals: no challenge used, no adoption.
    assert counts()["challenges"] == 2 and not first.adoptions.exists() and not second.adoptions.exists()


@pytest.mark.django_db
def test_9kg_29_the_forwarded_identity_counts_only_in_proxy_mode_and_a_missing_or_invalid_one_refuses_issuance(
        settings, caplog):
    client = Client()
    link = link_for(intake(client, email="early@example.test"))  # issued while the identity is the peer
    settings.CATALYST_CLIENT_IDENTITY = "proxy"
    settings.CATALYST_THROTTLE_INTAKE_PER_CLIENT = 1
    before = counts()
    for forwarded in (None, "", "not-an-address", f"{PROXY_CLIENT}, {OTHER_CLIENT}"):
        response = post(client) if forwarded is None else post_from(client, forwarded)
        assert response.status_code == 503 and b"Please try again" in response.content and "Location" not in response
    assert counts() == before  # nothing recorded without a client identity
    assert "client identity missing; issuance refused" in caplog.text
    assert post_from(client, PROXY_CLIENT).status_code == 302
    assert post_from(client, PROXY_CLIENT).status_code == 429  # its bucket is full
    assert post_from(client, OTHER_CLIENT).status_code == 302  # another client, its own bucket
    assert client.get(path_of(link)).status_code == 200  # a read with no identity is still served
    assert post_confirm(client, link, "ignored").status_code == 503  # a write with no identity is refused
    # Direct mode: the peer is the identity; a forged forwarded header moves nothing into another bucket.
    settings.CATALYST_CLIENT_IDENTITY = "direct"
    settings.CATALYST_THROTTLE_INTAKE_PER_CLIENT = 2
    RequestThrottle.objects.all().delete()
    assert post_from(client, PROXY_CLIENT).status_code == 302
    assert post_from(client, OTHER_CLIENT).status_code == 302
    assert post_from(client, THIRD_CLIENT).status_code == 429  # all three were one peer
    keys_carry_no_value(PROXY_CLIENT, OTHER_CLIENT, "127.0.0.1")


def store_down(execute, sql, params, many, context):
    if "accounts_requestthrottle" in sql:
        raise DatabaseError("injected throttle outage")
    return execute(sql, params, many, context)


@pytest.mark.django_db
def test_9kg_29_an_unavailable_throttle_store_fails_closed_for_issuance_and_open_for_reading(settings, caplog):
    settings.CATALYST_AGREEMENT_WEBHOOK_SECRETS = ["synthetic-webhook-secret"]
    client = Client()
    app = intake(client)
    link, v1 = link_for(app), version(app, 1).public_id
    before = counts()
    with connection.execute_wrapper(store_down):
        refused = post(client, email="bob@example.test")
        assert refused.status_code == 503 and b"Please try again" in refused.content and "Location" not in refused
        assert client.get(path_of(link)).status_code == 200  # reading: open
        assert client.get("/setup/not-a-real-token/").status_code == 404
        assert post_confirm(client, link, v1).status_code == 503  # issuance: closed
        assert client.post("/setup/not-a-real-token/", {"password": "x", "confirm": "x"}).status_code == 503
        hook = client.post(HOOK, data=json.dumps({"event": "x"}), content_type="application/json",
                           HTTP_X_DOCUMENSO_SECRET="synthetic-webhook-secret")
        assert hook.status_code == 503 and hook.content == b""
    assert counts() == before and not app.adoptions.exists()
    assert "throttle store unavailable (DatabaseError); issuance refused" in caplog.text
    assert "throttle store unavailable (DatabaseError); read admitted" in caplog.text
    assert "injected throttle outage" not in caplog.text and "bob@example.test" not in caplog.text
    assert post(client, email="bob@example.test").status_code == 302  # the store is back: so is the form
    assert post_confirm(client, link, v1).status_code == 200


@pytest.mark.django_db
def test_9kg_29_the_webhook_is_limited_per_client_before_the_secret_is_compared(settings):
    settings.CATALYST_AGREEMENT_WEBHOOK_SECRETS = ["synthetic-webhook-secret"]
    settings.CATALYST_THROTTLE_WEBHOOK_PER_CLIENT = 2
    hits = [Client().post(HOOK, data="{}", content_type="application/json", HTTP_X_DOCUMENSO_SECRET="wrong") for _ in range(3)]
    assert [h.status_code for h in hits] == [401, 401, 429] and hits[-1].content == b""
    assert Client().post(HOOK, data="{}", content_type="application/json",
                         HTTP_X_DOCUMENSO_SECRET="synthetic-webhook-secret").status_code == 429  # the right secret too


def test_9kg_29_stale_buckets_are_swept_with_the_staff_sessions(privileged_reset):
    assert throttle.admit("probe", "fresh", 5) and throttle.admit("probe", "stale", 5)
    RequestThrottle.objects.filter(key=throttle.key("probe", "stale")).update(updated_at=Now() - timedelta(days=2))
    assert staff_access.schedule_session_cleanup()
    assert ledger.run_one({staff_access.CLEAR_SESSIONS: staff_access.ClearSessions()})
    assert list(RequestThrottle.objects.values_list("key", flat=True)) == [throttle.key("probe", "fresh")]
