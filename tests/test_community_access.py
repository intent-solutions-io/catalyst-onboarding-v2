"""Synthetic PostgreSQL membership obligations; no real Discord credentials or calls."""

import hashlib
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models.functions import Now
from django.utils import timezone

from applications.models import Application
from config import guards
from provisioning import community, community_restore
from provisioning.community_adapter import (
    CommunityError,
    DiscordAPI,
    HTTPSDiscord,
    LiveDiscord,
)
from provisioning.community_handlers import ReconcileCommunity, RevokeCommunity
from provisioning.models import CommunityAccess, CommunityReceipt
from workflow import journal, ledger
from workflow.models import PendingAction

GUILD, USER = "111111111111111111", "222222222222222222"
ROLES = {
    "Member": "333333333333333331",
    "Certified": "333333333333333332",
    "Leaders": "333333333333333333",
}
EPOCH = "2026-10-27T08:00:00+00:00"
DIGEST = hashlib.sha256(b"synthetic independently reviewed evidence").hexdigest()
REGISTRY = {
    community.RECONCILE: ReconcileCommunity(),
    community.REVOKE: RevokeCommunity(),
}


class FakeDiscord(DiscordAPI):
    roles_present = set()
    present = True
    joined = EPOCH
    writes = []
    after_write = None

    def __init__(self):
        super().__init__(GUILD, ROLES, self.exchange)

    def exchange(self, path, method, payload):
        assert payload is None
        assert not connection.in_atomic_block, "provider holds a product row lock"
        assert path.startswith(f"/guilds/{GUILD}/members/{USER}")
        cls = type(self)
        if method == "GET":
            if not cls.present:
                raise CommunityError("not_found", status=404, provider_code=10007)
            return {
                "user": {"id": USER},
                "roles": list(cls.roles_present),
                "joined_at": cls.joined,
            }
        cls.writes.append((method, path))
        rid = path.rsplit("/", 1)[-1]
        if method == "PUT":
            cls.roles_present.add(rid)
        elif method == "DELETE":
            cls.roles_present.discard(rid)
        else:
            raise AssertionError("No broad member patch is allowed")
        callback, cls.after_write = cls.after_write, None
        if callback:
            callback()


@pytest.fixture
def environment(settings, monkeypatch, privileged_reset):
    settings.CATALYST_COMMUNITY_IDENTITY_KEY = hashlib.sha256(
        b"synthetic separate identity encryption key"
    ).hexdigest()
    settings.CATALYST_COMMUNITY_ADAPTER = "tests.test_community_access.FakeDiscord"
    settings.CATALYST_COMMUNITY_GRANTS_ENABLED = True
    settings.CATALYST_COMMUNITY_GUILD_ID = GUILD
    monkeypatch.setattr("agreements.completion.fresh_read_problem", lambda app: None)
    FakeDiscord.roles_present, FakeDiscord.writes = set(), []
    FakeDiscord.present, FakeDiscord.joined, FakeDiscord.after_write = True, EPOCH, None
    app = Application.objects.create(
        email="member@example.test",
        email_key="member@example.test",
        display_name="Synthetic",
        stage="active",
        contact_verified_at=timezone.now(),
    )
    reviewer = SimpleNamespace(
        pk=17,
        is_authenticated=True,
        is_active=True,
        is_superuser=False,
        has_perm=lambda permission: (
            permission == "provisioning.approve_community_access"
        ),
    )
    return app, reviewer


def approve(env, **kwargs):
    app, reviewer = env
    return community.approve(
        app.pk,
        reviewer,
        guild_id=GUILD,
        user_id=USER,
        joined_at=EPOCH,
        identity_evidence=DIGEST,
        decision_evidence=DIGEST,
        **kwargs,
    )


def work():
    return ledger.run_one(REGISTRY)


def test_independent_grants_and_exact_single_role_endpoints(environment):
    access = approve(environment, certified_evidence=DIGEST, leaders_evidence=DIGEST)
    assert work()
    access.refresh_from_db()
    assert set(access.verified_roles) == set(ROLES)
    assert FakeDiscord.roles_present == set(ROLES.values())
    assert len(FakeDiscord.writes) == 3
    assert all(
        method == "PUT" and "/roles/" in path for method, path in FakeDiscord.writes
    )
    assert not work()


def test_encrypted_identity_and_no_raw_ids_in_history_or_receipts(environment):
    access = approve(environment)
    work()
    assert (
        USER not in access.sealed_identity
        and community.identity(access)["user_id"] == USER
    )
    with connection.cursor() as cursor:
        for table in (
            "provisioning_communityaccess",
            "provisioning_communityreceipt",
            "workflow_pendingaction",
            "applications_applicationevent",
        ):
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE row_to_json({table})::text LIKE %s",
                [f"%{USER}%"],
            )
            assert cursor.fetchone()[0] == 0


def test_named_staff_permission_and_independent_evidence_required(environment):
    app, reviewer = environment
    reviewer.has_perm = lambda permission: False
    with pytest.raises(PermissionDenied):
        approve(environment)
    assert not CommunityAccess.objects.exists()
    reviewer.has_perm = lambda permission: True
    with pytest.raises(CommunityError, match="independent"):
        approve(environment, certified_evidence="claimed in chat")


def test_disabled_grants_do_not_disable_protective_revocation(environment, settings):
    access = approve(environment, certified_evidence=DIGEST, leaders_evidence=DIGEST)
    work()
    settings.CATALYST_COMMUNITY_GRANTS_ENABLED = False
    community.revoke(environment[0].pk, environment[1])
    assert work()
    access.refresh_from_db()
    assert access.revoked and access.removal_verified
    assert not FakeDiscord.roles_present
    assert (
        access.requires_review
    )  # other roles/member overwrites are not claimed removed


def test_positive_eligibility_is_checked_again_before_grants(environment, monkeypatch):
    access = approve(environment)
    monkeypatch.setattr(
        "agreements.completion.fresh_read_problem", lambda app: "provider_unavailable"
    )
    work()
    assert not FakeDiscord.writes
    assert PendingAction.objects.get(input_ref=str(access.public_id)).status == "held"


def test_absent_member_is_not_auto_joined_and_rejoin_needs_new_review(environment):
    access = approve(environment)
    FakeDiscord.present = False
    work()
    access.refresh_from_db()
    assert access.requires_review and not FakeDiscord.writes
    FakeDiscord.present = True
    with pytest.raises(CommunityError, match="readmission"):
        approve(environment)
    approve(environment, reapprove=True)
    work()
    assert FakeDiscord.roles_present == {ROLES["Member"]}


def test_changed_membership_epoch_and_manual_removal_are_not_healed(environment):
    access = approve(environment)
    work()
    FakeDiscord.roles_present.clear()
    approve(environment)
    work()
    access.refresh_from_db()
    assert access.requires_review and len(FakeDiscord.writes) == 1
    FakeDiscord.joined = "2026-10-28T08:00:00+00:00"
    approve(environment, reapprove=True)
    work()
    assert len(FakeDiscord.writes) == 1


def test_revoke_racing_provider_acceptance_leaves_protective_job(environment):
    access = approve(environment, certified_evidence=DIGEST)
    FakeDiscord.after_write = lambda: community.revoke(
        environment[0].pk, environment[1]
    )
    work()
    assert PendingAction.objects.filter(kind=community.REVOKE, status="queued").exists()
    work()
    access.refresh_from_db()
    assert access.revoked and access.removal_verified and not FakeDiscord.roles_present


def test_late_grant_after_a_finished_revocation_creates_a_new_protective_round(
    environment,
):
    access = approve(environment)

    def finish_removal_then_late_grant():
        community.revoke(environment[0].pk, environment[1])
        assert work()  # another worker completes the restrictive job first
        FakeDiscord.roles_present.add(
            ROLES["Member"]
        )  # stale provider request lands after that readback

    FakeDiscord.after_write = finish_removal_then_late_grant
    work()
    access.refresh_from_db()
    assert access.revoked and not access.removal_verified
    assert (
        PendingAction.objects.filter(kind=community.REVOKE, status="queued").count()
        == 1
    )
    work()
    assert not FakeDiscord.roles_present


def test_accepted_timeout_is_visible_and_review_reads_before_another_grant(environment):
    access = approve(environment)

    def uncertain():
        raise TimeoutError("synthetic dropped response")

    FakeDiscord.after_write = uncertain
    work()
    action = PendingAction.objects.get(input_ref=str(access.public_id))
    assert action.status == "queued" and action.last_error == "provider_unknown"
    PendingAction.objects.filter(pk=action.pk).update(due_at=Now())
    work()
    assert len(FakeDiscord.writes) == 1


def test_stale_worker_cannot_record_completion(environment):
    approve(environment)
    claim = ledger.claim_next(REGISTRY)
    PendingAction.objects.filter(pk=claim.id).update(
        lease_token=__import__("uuid").uuid4()
    )
    REGISTRY[community.RECONCILE].run(claim)
    assert not FakeDiscord.writes
    assert not CommunityReceipt.objects.filter(outcome="roles_verified").exists()


def test_restrictive_journal_replay_and_unknown_binding_hold(
    environment, settings, tmp_path
):
    settings.CATALYST_EFFECT_JOURNAL_DIR = str(tmp_path)
    access = approve(environment)
    work()
    community.revoke(environment[0].pk, environment[1])
    entries = [entry for entry in journal.read() if entry.kind.startswith("community_")]
    CommunityAccess.objects.filter(pk=access.pk).update(
        revoked=False, revision=1, desired_roles=["Member"]
    )
    opened = []
    with transaction.atomic(), journal.replaying():
        report = community_restore.replay(
            entries, lambda *args, **kwargs: opened.append(args) or True
        )
    access.refresh_from_db()
    assert report["replayed"] and access.revoked
    from dataclasses import replace

    unknown = replace(entries[-1], key="community:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    community_restore.replay(
        [unknown], lambda *args, **kwargs: opened.append(args) or True
    )
    assert opened[-1][0] == "restore_effect_community_missing"


def test_live_factory_requires_explicit_reviewed_configuration_and_stays_default_off(
    settings, monkeypatch
):
    settings.CATALYST_ENV = "production"
    settings.CATALYST_COMMUNITY_ADAPTER = "provisioning.community_adapter.LiveDiscord"
    settings.CATALYST_COMMUNITY_IDENTITY_KEY = ""
    assert guards.community_problems(settings, {})
    settings.CATALYST_COMMUNITY_ADAPTER = ""
    settings.CATALYST_COMMUNITY_GRANTS_ENABLED = False
    assert not guards.community_problems(settings, {})
    separate_key = hashlib.sha256(b"synthetic historical key collision").hexdigest()
    settings.CATALYST_COMMUNITY_IDENTITY_KEY = separate_key
    assert not guards.community_problems(settings, {})
    for name, value in (
        ("CATALYST_ERASURE_PREVIOUS_KEYS", [separate_key]),
        ("CATALYST_CUSTODY_NEXT_WRAPPING_KEY", separate_key),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(settings, name, value)
            assert (
                "Community identity key must be independent"
                in guards.community_problems(settings, {})
            )


def test_transport_rejects_arbitrary_endpoints_before_network():
    api = HTTPSDiscord("synthetic_access_credential_123456")
    with pytest.raises(CommunityError, match="endpoint_refused"):
        api("/channels/333333333333333333/messages", "POST", {"content": "no"})


def test_https_transport_verifies_tls_bounds_response_and_never_follows_redirect(
    monkeypatch,
):
    import ssl

    calls = []

    class Response:
        status = 302

        def read(self, limit):
            assert limit == 65537
            return b'{"private":"synthetic provider text"}'

    class Connection:
        def __init__(self, host, *, timeout, context):
            assert host == "discord.com" and timeout == 10
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname

        def request(self, method, path, headers):
            calls.append((method, path))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        "provisioning.community_adapter.http.client.HTTPSConnection", Connection
    )
    transport = HTTPSDiscord("synthetic_access_credential_123456")
    with pytest.raises(CommunityError) as error:
        transport(f"/guilds/{GUILD}/members/{USER}", "GET", None)
    assert error.value.status == 302 and "private" not in str(error.value)
    assert calls == [("GET", f"/api/v10/guilds/{GUILD}/members/{USER}")]
    Response.status = 200
    monkeypatch.setattr(Response, "read", lambda self, limit: b"x" * limit)
    with pytest.raises(CommunityError, match="too_large"):
        transport(f"/guilds/{GUILD}/members/{USER}", "GET", None)


@pytest.mark.parametrize(
    "status,code,absent",
    [
        (404, 10007, True),
        (404, 10004, False),
        (404, None, False),
        (403, 10007, False),
        (403, 50001, False),
        (429, None, False),
        (500, None, False),
    ],
)
def test_only_authoritative_not_found_is_absence(status, code, absent):
    def call(*args):
        raise CommunityError("provider_refused", status=status, provider_code=code)

    api = DiscordAPI(GUILD, ROLES, call)
    if absent:
        assert api.member(USER) is None
    else:
        with pytest.raises(CommunityError):
            api.member(USER)


@pytest.mark.parametrize(
    "body,expected",
    [
        (b'{"code":10007,"message":"private text"}', 10007),
        (b'{"code":10004,"message":"private text"}', 10004),
        (b'{"code":"10007"}', None),
        (b"not-json", None),
    ],
)
def test_http_error_preserves_only_the_numeric_provider_code(
    monkeypatch, body, expected
):
    class Response:
        status = 404

        def read(self, limit):
            return body

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        "provisioning.community_adapter.http.client.HTTPSConnection", Connection
    )
    transport = HTTPSDiscord("synthetic_access_credential_123456")
    with pytest.raises(CommunityError) as error:
        transport(f"/guilds/{GUILD}/members/{USER}", "GET", None)
    assert error.value.provider_code == expected and error.value.status == 404
    assert str(error.value) == "provider_refused" and "private" not in repr(
        error.value.__dict__
    )


@pytest.mark.parametrize("status,code", [(404, 10004), (404, None), (403, 50001)])
def test_guild_or_access_failure_never_verifies_removal_or_allows_offboarding(
    environment, monkeypatch, status, code
):
    access = approve(environment)
    work()
    community.revoke(environment[0].pk, environment[1])

    def unavailable(self, path, method, payload):
        assert method == "GET"
        raise CommunityError("provider_refused", status=status, provider_code=code)

    monkeypatch.setattr(FakeDiscord, "exchange", unavailable)
    work()
    access.refresh_from_db()
    assert not access.removal_verified and access.requires_review
    assert FakeDiscord.roles_present == {ROLES["Member"]}
    with pytest.raises(CommunityError, match="not_verified"):
        community.confirm_offboarding(environment[0].pk, environment[1], DIGEST)


@pytest.mark.parametrize(
    "actor_permissions,highest,allowed",
    [
        (1 << 28, 5, True),
        ((1 << 28) | (1 << 3), 5, False),
        (0, 5, False),
        (1 << 28, 1, False),
    ],
)
def test_live_boundary_checks_scoped_bot_and_role_hierarchy(
    actor_permissions, highest, allowed
):
    bot, bot_role = "444444444444444444", "555555555555555555"
    writes = []

    def call(path, method, payload):
        if path == "/users/@me":
            return {"id": bot, "bot": True}
        if path.endswith("/roles") and method == "GET":
            return [
                {"id": GUILD, "permissions": "0", "position": 0, "managed": False},
                {
                    "id": bot_role,
                    "permissions": str(actor_permissions),
                    "position": highest,
                    "managed": True,
                },
                *[
                    {"id": rid, "permissions": "0", "position": 1, "managed": False}
                    for rid in ROLES.values()
                ],
            ]
        if path.endswith("/members/" + bot):
            return {"roles": [bot_role]}
        writes.append((method, path))

    api = LiveDiscord.__new__(LiveDiscord)
    DiscordAPI.__init__(api, GUILD, ROLES, call)
    api._scope_verified = False
    if allowed:
        api.grant(USER, "Member")
        assert len(writes) == 1
    else:
        with pytest.raises(CommunityError):
            api.grant(USER, "Member")
        assert not writes


def test_two_workers_cannot_claim_the_same_obligation(environment):
    from concurrent.futures import ThreadPoolExecutor

    approve(environment)

    def claim():
        try:
            return ledger.claim_next(REGISTRY)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(result is not None for result in results) == 1


def test_stale_review_revision_cannot_overwrite_a_newer_restriction(environment):
    access = approve(environment)
    community.revoke(environment[0].pk, environment[1])
    with pytest.raises(CommunityError, match="revision_changed"):
        approve(environment, reapprove=True, expected_revision=access.revision)


def test_invalid_role_configuration_is_rejected_before_any_call():
    with pytest.raises(CommunityError):
        DiscordAPI(GUILD, dict(ROLES, Certified=ROLES["Member"]), lambda *args: None)


def test_new_binding_cannot_claim_an_existing_verified_discord_identity(environment):
    approve(environment)
    app = Application.objects.create(
        email="other@example.test",
        email_key="other@example.test",
        display_name="Other",
        stage="active",
        contact_verified_at=timezone.now(),
    )
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        approve((app, environment[1]))
    assert CommunityAccess.objects.count() == 1


def test_erasure_waits_for_managed_removal_and_residual_review(
    environment, privileged_reset
):
    from provisioning import closure
    from psycopg import errors

    access = approve(environment)
    work()
    app, reviewer = environment
    with transaction.atomic():
        locked = Application.objects.select_for_update().get(pk=app.pk)
        closure.close_locked(
            locked, "closed", "synthetic verified closure", "user:17", "staff"
        )
    work()
    access.refresh_from_db()
    assert access.removal_verified and access.requires_review
    retention = privileged_reset.connect("retention", autocommit=True)
    sql = "SELECT public.catalyst_erase(%s, 'owner_approved', 'confirmed_request', ARRAY['provisioning_records'])"
    with pytest.raises(errors.DatabaseError) as failure:
        retention.execute(sql, [app.public_ref])
    assert failure.value.sqlstate == "CE005"
    community.confirm_offboarding(app.pk, reviewer, DIGEST)
    retention.execute(sql, [app.public_ref])
    access.refresh_from_db()
    assert access.sealed_identity == "[erased]" and access.identity_key == ""
    with pytest.raises(CommunityError, match="identity_unavailable"):
        community.identity(access)


def test_manual_removal_after_partial_success_is_not_hidden_by_another_unknown_role(
    environment,
):
    access = approve(environment, certified_evidence=DIGEST)

    def timeout():
        raise TimeoutError("synthetic second role outcome lost")

    def after_first():
        FakeDiscord.after_write = timeout

    FakeDiscord.after_write = after_first
    work()
    access.refresh_from_db()
    assert access.verified_roles == ["Member"]
    FakeDiscord.roles_present.discard(ROLES["Member"])
    PendingAction.objects.filter(
        input_ref=str(access.public_id), status="queued"
    ).update(due_at=Now())
    work()
    assert len(FakeDiscord.writes) == 2
    assert PendingAction.objects.get(input_ref=str(access.public_id)).status == "held"


def test_activation_reconsiders_an_existing_held_entitlement(environment):
    app, _ = environment
    Application.objects.filter(pk=app.pk).update(stage="provisioning")
    access = approve(environment)
    work()
    assert PendingAction.objects.get(input_ref=str(access.public_id)).status == "held"
    Application.objects.filter(pk=app.pk).update(stage="active")
    with transaction.atomic():
        community.activation_locked(
            Application.objects.select_for_update().get(pk=app.pk)
        )
    work()
    assert FakeDiscord.roles_present == {ROLES["Member"]}


def test_complete_reviewed_live_configuration_can_operate_with_grants_disabled(
    settings, monkeypatch
):
    settings.CATALYST_ENV = "production"
    settings.CATALYST_COMMUNITY_ADAPTER = "provisioning.community_adapter.LiveDiscord"
    settings.CATALYST_COMMUNITY_IDENTITY_KEY = hashlib.sha256(
        b"synthetic configuration key"
    ).hexdigest()
    settings.CATALYST_COMMUNITY_BOT_TOKEN = "synthetic_access_credential_123456"
    settings.CATALYST_COMMUNITY_LIVE_AUTHORITY = DIGEST
    settings.CATALYST_COMMUNITY_GUILD_ID = GUILD
    settings.CATALYST_COMMUNITY_ROLE_IDS = ROLES
    settings.CATALYST_COMMUNITY_GRANTS_ENABLED = False
    monkeypatch.setattr(guards, "_process_kind", lambda: "worker")
    assert not guards.community_problems(settings, {})
    monkeypatch.setattr(guards, "_process_kind", lambda: "web")
    assert guards.community_problems(settings, {})


def test_staff_command_previews_and_applies_exact_review_without_provider_calls(
    environment, tmp_path, monkeypatch
):
    import json
    from io import StringIO
    from django.core.management import call_command
    from django.core.management.base import CommandError

    app, reviewer = environment
    monkeypatch.setattr(
        "provisioning.management.commands.catalyst_community_access.get_user_model",
        lambda: SimpleNamespace(objects=SimpleNamespace(get=lambda **kwargs: reviewer)),
    )
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "guild_id": GUILD,
                "user_id": USER,
                "joined_at": EPOCH,
                "identity_evidence": DIGEST,
                "decision_evidence": DIGEST,
            }
        )
    )
    path.chmod(0o600)
    options = {
        "application": str(app.public_ref),
        "reviewer": reviewer.pk,
        "decision_file": str(path),
    }
    output = StringIO()
    call_command("catalyst_community_access", "approve", stdout=output, **options)
    preview = json.loads(output.getvalue())
    assert not CommunityAccess.objects.exists() and USER not in output.getvalue()
    with pytest.raises(CommandError):
        call_command(
            "catalyst_community_access",
            "approve",
            apply=True,
            expected_digest="stale",
            **options,
        )
    call_command(
        "catalyst_community_access",
        "approve",
        apply=True,
        expected_digest=preview["sha256"],
        stdout=StringIO(),
        **options,
    )
    assert CommunityAccess.objects.count() == 1 and not FakeDiscord.writes


@pytest.mark.parametrize("paused", [False, True])
def test_partial_downgrade_remains_protective_with_grants_disabled_or_subject_paused(
    environment, settings, paused
):
    from workflow.models import AutomationPause

    access = approve(environment, certified_evidence=DIGEST)
    work()
    if paused:
        AutomationPause.objects.create(
            subject_type="application",
            subject_id=environment[0].public_ref,
            reason="synthetic hold",
            actor_ref="user:17",
        )
    else:
        settings.CATALYST_COMMUNITY_GRANTS_ENABLED = False
    approve(environment)
    assert work()
    access.refresh_from_db()
    assert FakeDiscord.roles_present == {ROLES["Member"]}
    assert (
        not access.removal_verified
    )  # partial restriction is not complete offboarding


def test_stale_offboarding_review_cannot_clear_a_newer_revocation(environment):
    access = approve(environment)
    work()
    community.revoke(environment[0].pk, environment[1])
    work()
    access.refresh_from_db()
    old_revision = access.revision
    community.revoke(environment[0].pk, environment[1])
    work()
    with pytest.raises(CommunityError, match="revision_changed"):
        community.confirm_offboarding(
            environment[0].pk, environment[1], DIGEST, expected_revision=old_revision
        )
    access.refresh_from_db()
    assert access.requires_review


def test_reintroduced_role_during_last_removal_is_not_false_confirmation(environment):
    access = approve(environment)
    work()
    community.revoke(environment[0].pk, environment[1])
    FakeDiscord.after_write = lambda: FakeDiscord.roles_present.add(ROLES["Certified"])
    work()
    access.refresh_from_db()
    assert not access.removal_verified and FakeDiscord.roles_present == {
        ROLES["Certified"]
    }
    job = PendingAction.objects.get(
        kind=community.REVOKE, input_ref=str(access.public_id)
    )
    assert job.status == "queued" and job.last_error == "final_role_set_mismatch"
    PendingAction.objects.filter(pk=job.pk).update(due_at=Now())
    work()
    assert not FakeDiscord.roles_present


def test_required_role_disappearing_during_a_later_grant_requires_review(environment):
    access = approve(environment, certified_evidence=DIGEST)

    def remove_during_second_write():
        FakeDiscord.roles_present.discard(ROLES["Member"])

    def first():
        FakeDiscord.after_write = remove_during_second_write

    FakeDiscord.after_write = first
    work()
    access.refresh_from_db()
    assert access.requires_review
    assert PendingAction.objects.get(input_ref=str(access.public_id)).status == "held"
    assert not access.receipts.filter(outcome="roles_verified").exists()


def test_binding_rejects_a_guild_outside_configured_scope(environment, settings):
    settings.CATALYST_COMMUNITY_GUILD_ID = "666666666666666666"
    with pytest.raises(CommunityError, match="outside_configured_scope"):
        approve(environment)
    assert not CommunityAccess.objects.exists()


def test_partial_restriction_replay_never_recreates_new_positive_grants(
    environment, settings, tmp_path
):
    settings.CATALYST_EFFECT_JOURNAL_DIR = str(tmp_path)
    access = approve(environment, certified_evidence=DIGEST)
    work()
    approve(
        environment, leaders_evidence=DIGEST
    )  # remove Certified; separately approve Leaders
    restrictions = [
        entry for entry in journal.read() if entry.kind == "community_restricted"
    ]
    assert restrictions and all(
        entry.data["roles"] == ["Member"] for entry in restrictions
    )
    CommunityAccess.objects.filter(pk=access.pk).update(
        revision=1, desired_roles=["Member", "Certified"]
    )
    with transaction.atomic(), journal.replaying():
        community_restore.replay(restrictions, lambda *args, **kwargs: True)
    access.refresh_from_db()
    assert access.desired_roles == ["Member"] and access.requires_review
    opened = []
    community_restore.read_members(lambda *args, **kwargs: opened.append(args) or True)
    assert opened and opened[0][0] == "restore_effect_community"


def test_empty_restriction_during_readmission_replays_as_runnable_full_removal(
    environment,
):
    access = approve(environment, certified_evidence=DIGEST)
    work()
    community.revoke(environment[0].pk, environment[1])
    # Readmission changes the decision before the existing remote roles are removed.
    # It must not make an empty restore ceiling an invalid positive entitlement.
    approve(environment, reapprove=True)
    restrictions = [
        entry for entry in journal.read() if entry.kind == "community_restricted"
    ]
    assert restrictions and all(entry.data["roles"] == [] for entry in restrictions)
    with transaction.atomic(), journal.replaying():
        community_restore.replay(restrictions, lambda *args, **kwargs: True)
    access.refresh_from_db()
    assert access.revoked and community.target(access) == set()
    assert work()
    access.refresh_from_db()
    assert not FakeDiscord.roles_present and access.removal_verified
