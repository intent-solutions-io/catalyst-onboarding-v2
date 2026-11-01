"""Reviewed community decisions, atomically enqueued in the existing job ledger."""

import hashlib
import hmac
import json
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, TERMINAL_STAGES
from correspondence.staff_items import event
from workflow import journal
from workflow.models import PendingAction

from . import services
from .community_adapter import CommunityError, ID, ROLES
from .models import CommunityAccess

RECONCILE, REVOKE = "community_reconcile", "community_revoke"
HASH = re.compile(r"[0-9a-f]{64}\Z")


def key():
    value = getattr(settings, "CATALYST_COMMUNITY_IDENTITY_KEY", "")
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise CommunityError("identity_key_unavailable")
    return bytes.fromhex(value)


def seal(guild, user_id, joined_at):
    nonce = os.urandom(12)
    plain = json.dumps(
        {"user_id": user_id, "joined_at": joined_at}, sort_keys=True
    ).encode()
    return (nonce + AESGCM(key()).encrypt(nonce, plain, guild.encode())).hex()


def identity(access):
    try:
        raw = bytes.fromhex(access.sealed_identity)
        result = json.loads(
            AESGCM(key()).decrypt(raw[:12], raw[12:], access.guild_id.encode())
        )
        if set(result) != {"user_id", "joined_at"} or not ID.fullmatch(
            result["user_id"]
        ):
            raise ValueError
        return result
    except Exception:
        raise CommunityError("identity_unavailable") from None


def enqueue(access, *, revoke=False):
    kind = REVOKE if revoke else RECONCILE
    return PendingAction.objects.get_or_create(
        idempotency_key=f"{kind}:{access.public_id}:{access.revision}",
        defaults={
            "kind": kind,
            "subject_type": "application",
            "subject_id": access.application.public_ref,
            "input_ref": str(access.public_id),
            "max_attempts": 5,
        },
    )[0]


def approve(
    application_id,
    user,
    *,
    guild_id,
    user_id,
    joined_at,
    identity_evidence,
    decision_evidence,
    certified_evidence="",
    leaders_evidence="",
    reapprove=False,
    expected_revision=None,
):
    """Staff attests independently verified evidence; a digest alone proves nothing.

    No public endpoint accepts these fields. No role grant occurs in this service.
    Reapproval is a new explicit decision, never inferred from a rejoin or stage.
    """
    services.require(user, "approve_community_access")
    if type(reapprove) is not bool:
        raise CommunityError("invalid_reapproval")
    if not ID.fullmatch(guild_id) or not ID.fullmatch(user_id):
        raise CommunityError("invalid_identity")
    if guild_id != getattr(settings, "CATALYST_COMMUNITY_GUILD_ID", ""):
        raise CommunityError("guild_outside_configured_scope")
    from django.utils.dateparse import parse_datetime

    if not isinstance(joined_at, str) or parse_datetime(joined_at) is None:
        raise CommunityError("invalid_membership_epoch")
    if any(
        not isinstance(v, str) or not HASH.fullmatch(v)
        for v in (identity_evidence, decision_evidence)
    ):
        raise CommunityError("review_evidence_required")
    if any(
        v and (not isinstance(v, str) or not HASH.fullmatch(v))
        for v in (certified_evidence, leaders_evidence)
    ):
        raise CommunityError("invalid_independent_evidence")
    roles = (
        ["Member"]
        + (["Certified"] if certified_evidence else [])
        + (["Leaders"] if leaders_evidence else [])
    )
    lookup = hmac.new(
        key(), f"{guild_id}:{user_id}".encode(), hashlib.sha256
    ).hexdigest()
    with transaction.atomic():
        app = Application.objects.select_for_update().get(pk=application_id)
        if app.stage in TERMINAL_STAGES or app.contact_verified_at is None:
            raise CommunityError("application_not_eligible")
        access = (
            CommunityAccess.objects.select_for_update().filter(application=app).first()
        )
        previous_roles = (
            set(access.desired_roles) | set(access.verified_roles) if access else set()
        )
        if expected_revision is not None and expected_revision != (
            access.revision if access else 0
        ):
            raise CommunityError("decision_revision_changed")
        fields = {
            "desired_roles": roles,
            "identity_evidence": identity_evidence,
            "decision_evidence": decision_evidence,
            "certified_evidence": certified_evidence,
            "leaders_evidence": leaders_evidence,
            "reviewed_by": services.actor(user),
            "revoked": False,
            "removal_verified": False,
            "requires_review": False,
            "updated_at": Now(),
        }
        if access:
            if access.guild_id != guild_id or access.identity_key != lookup:
                raise CommunityError("binding_replacement_requires_review")
            changed_epoch = identity(access)["joined_at"] != joined_at
            if (
                access.revoked or access.requires_review or changed_epoch
            ) and not reapprove:
                raise CommunityError("explicit_readmission_required")
            fields["revision"] = access.revision + 1
            restricted_roles = sorted(set(access.desired_roles) & set(roles))
            if previous_roles - set(roles):
                journal.prepare(
                    "community_restricted",
                    f"community:{access.public_id}",
                    {"revision": fields["revision"], "roles": restricted_roles},
                )
            if reapprove:
                fields.update(
                    sealed_identity=seal(guild_id, user_id, joined_at),
                    verified_roles=[],
                )
            CommunityAccess.objects.filter(pk=access.pk).update(**fields)
            access.refresh_from_db()
            if previous_roles - set(roles):
                journal.record(
                    "community_restricted",
                    f"community:{access.public_id}",
                    {
                        "revision": access.revision,
                        "phase": "done",
                        "roles": restricted_roles,
                    },
                )
        else:
            access = CommunityAccess.objects.create(
                application=app,
                guild_id=guild_id,
                identity_key=lookup,
                sealed_identity=seal(guild_id, user_id, joined_at),
                **fields,
            )
        event(
            app,
            "community_decision_reviewed",
            {"binding": str(access.public_id), "revision": access.revision},
            actor_ref=services.actor(user),
        )
        if previous_roles - set(roles):
            enqueue(
                access, revoke=True
            )  # restrictive work remains runnable while grants are held
        enqueue(access)
        return access


def revoke_locked(application, *, force=False):
    """Called with the application locked, also during closure and restore replay."""
    access = (
        CommunityAccess.objects.select_for_update()
        .filter(application=application)
        .first()
    )
    if access is None:
        return
    if not access.revoked or force:
        revision = access.revision + 1
        journal.prepare(
            "community_revoked", f"community:{access.public_id}", {"revision": revision}
        )
        CommunityAccess.objects.filter(pk=access.pk).update(
            revision=revision,
            revoked=True,
            desired_roles=[],
            requires_review=True,
            removal_verified=False,
            updated_at=Now(),
        )
        access.refresh_from_db()
        journal.record(
            "community_revoked",
            f"community:{access.public_id}",
            {"revision": revision, "phase": "done"},
        )
    PendingAction.objects.filter(
        kind=RECONCILE, input_ref=str(access.public_id), status__in=("queued", "held")
    ).update(status="cancelled", completed_at=Now(), updated_at=Now())
    enqueue(access, revoke=True)


def revoke(application_id, user, *, expected_revision=None):
    services.require(user, "approve_community_access")
    with transaction.atomic():
        app = Application.objects.select_for_update().get(pk=application_id)
        access = CommunityAccess.objects.filter(application=app).first()
        if expected_revision is not None and expected_revision != (
            access.revision if access else 0
        ):
            raise CommunityError("decision_revision_changed")
        revoke_locked(app, force=bool(access and access.revoked))


def activation_locked(application):
    access = CommunityAccess.objects.filter(
        application=application, revoked=False
    ).first()
    if access:
        action = enqueue(access)
        PendingAction.objects.filter(pk=action.pk, status="held").update(
            status="queued", due_at=Now(), updated_at=Now(), last_error=""
        )


def confirm_offboarding(application_id, user, evidence, *, expected_revision=None):
    """Staff attests that unmanaged roles/overwrites were separately reviewed.

    Verified removal of the three managed roles alone cannot authorize erasing the
    identity needed to investigate remaining access paths.
    """
    services.require(user, "approve_community_access")
    if not isinstance(evidence, str) or not HASH.fullmatch(evidence):
        raise CommunityError("offboarding_evidence_required")
    with transaction.atomic():
        app = Application.objects.select_for_update().get(pk=application_id)
        access = CommunityAccess.objects.select_for_update().get(application=app)
        if expected_revision is not None and access.revision != expected_revision:
            raise CommunityError("decision_revision_changed")
        if not access.revoked or not access.removal_verified:
            raise CommunityError("managed_revocation_not_verified")
        event(
            app,
            "community_offboarding_reviewed",
            {"binding": str(access.public_id), "evidence": evidence},
            actor_ref=services.actor(user),
        )
        CommunityAccess.objects.filter(pk=access.pk).update(
            requires_review=False, updated_at=Now()
        )


def target(access):
    """Reviewed role ceiling, independent from permission to add roles now."""
    if access.revoked or access.application.stage in TERMINAL_STAGES:
        return set()
    roles = set(access.desired_roles)
    if not roles <= set(ROLES) or "Member" not in roles:
        raise CommunityError("invalid_desired_roles")
    if "Certified" in roles and not HASH.fullmatch(access.certified_evidence):
        raise CommunityError("credential_not_verified")
    if "Leaders" in roles and not HASH.fullmatch(access.leaders_evidence):
        raise CommunityError("leadership_not_approved")
    return roles


def desired(access):
    roles = target(access)
    if not roles:
        return roles
    if (
        not getattr(settings, "CATALYST_COMMUNITY_GRANTS_ENABLED", False)
        or access.requires_review
    ):
        raise CommunityError("grants_held")
    if (
        access.application.stage != "active"
        or access.application.contact_verified_at is None
    ):
        raise CommunityError("application_not_active")
    from agreements.completion import fresh_read_problem

    if fresh_read_problem(access.application):
        raise CommunityError("agreements_not_current")
    return roles
