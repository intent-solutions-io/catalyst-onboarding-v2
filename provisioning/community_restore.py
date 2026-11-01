"""Restore review for Discord effects; no grants or provider mutations here."""

from django.db import transaction
from django.db.models.functions import Now

from . import community
from .community_adapter import CommunityError, provider, read_member
from .models import CommunityAccess


def replay(entries, opener):
    report = {"replayed": 0, "target_missing": 0}
    for entry in entries:
        reference = entry.key.removeprefix("community:")
        access = (
            CommunityAccess.objects.select_related("application")
            .filter(public_id=reference)
            .first()
        )
        if access is None:
            opener("restore_effect_community_missing", f"community:{reference}")
            report["target_missing"] += 1
            continue
        if (
            entry.kind == "community_revoked"
            and entry.data["revision"] >= access.revision
        ):
            CommunityAccess.objects.filter(pk=access.pk).update(
                revision=entry.data["revision"],
                revoked=True,
                desired_roles=[],
                requires_review=True,
                removal_verified=False,
                updated_at=Now(),
            )
            access.refresh_from_db()
            community.enqueue(access, revoke=True)
            report["replayed"] += 1
        elif (
            entry.kind == "community_restricted"
            and entry.data["revision"] >= access.revision
        ):
            # A prepared restriction may outlive a rolled-back approval. Intersect
            # the old ceiling; never recreate a positive approval from this log.
            ceiling = sorted(set(access.desired_roles) & set(entry.data["roles"]))
            CommunityAccess.objects.filter(pk=access.pk).update(
                revision=entry.data["revision"],
                desired_roles=ceiling,
                revoked=access.revoked or not ceiling,
                requires_review=True,
                removal_verified=False,
                updated_at=Now(),
            )
            access.refresh_from_db()
            community.enqueue(access, revoke=True)
            report["replayed"] += 1
    return report


def read_members(opener):
    rows = list(
        CommunityAccess.objects.select_related("application").exclude(identity_key="")
    )
    report = {"status": "ok", "checked": 0, "items": 0}
    if not rows:
        return report
    try:
        api = provider()
        for access in rows:
            if api.guild_id != access.guild_id:
                raise CommunityError("guild_mismatch")
            bound = community.identity(access)
            actual = read_member(api, bound["user_id"])
            wanted = community.target(access)
            conflict = (actual is None and bool(wanted)) or (
                actual is not None
                and (
                    actual["roles"] != wanted
                    or (wanted and actual["joined_at"] != bound["joined_at"])
                )
            )
            if conflict:
                with transaction.atomic():
                    CommunityAccess.objects.filter(pk=access.pk).update(
                        requires_review=True, updated_at=Now()
                    )
                    report["items"] += bool(
                        opener(
                            "restore_effect_community",
                            f"community:{access.public_id}",
                            application=access.application,
                        )
                    )
            report["checked"] += 1
    except Exception:
        report["status"] = "unreachable"
    return report
