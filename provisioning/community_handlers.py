"""Community provider work through the existing PostgreSQL worker and lease fence."""

from datetime import timedelta

from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, TERMINAL_STAGES
from correspondence.staff_items import event, open_item
from workflow import journal, ledger
from workflow.models import AutomationPause

from . import community
from .community_adapter import (
    CommunityError,
    ROLES,
    provider,
    read_member,
    grant_role,
    revoke_role,
)
from .models import CommunityAccess, CommunityReceipt

ITEM = "community_access_needs_review"


class ReconcileCommunity:
    kind = community.RECONCILE
    automated = True
    redeliverable = False

    def lock_subject(self, claim):
        Application.objects.select_for_update().filter(
            public_ref=claim.subject_id
        ).first()
        CommunityAccess.objects.select_for_update().filter(
            public_id=claim.input_ref
        ).first()

    def record(self, claim, kind, data):
        app = Application.objects.filter(public_ref=claim.subject_id).first()
        if app:
            event(app, kind, data, actor_ref=f"pending_action:{claim.id}")
            if kind in ("action_attempts_exhausted", "action_failed"):
                open_item(ITEM, f"community:{claim.input_ref}", application=app)

    def current(self, claim):
        return CommunityAccess.objects.select_related("application").get(
            public_id=claim.input_ref, application__public_ref=claim.subject_id
        )

    def finish(
        self,
        claim,
        access,
        code,
        *,
        status="done",
        roles=None,
        review=False,
        removed=False,
        retry_after=60,
    ):
        def write():
            # Completion cannot overwrite a later restrictive/approval revision.
            fields = {"updated_at": Now()}
            if roles is not None:
                fields["verified_roles"] = sorted(roles)
            if review:
                fields["requires_review"] = True
                open_item(
                    ITEM,
                    f"community:{access.public_id}",
                    application=access.application,
                )
            if removed:
                fields["removal_verified"] = True
            elif access.revoked:
                fields["removal_verified"] = False
            CommunityAccess.objects.filter(
                pk=access.pk, revision=access.revision
            ).update(**fields)
            CommunityReceipt.objects.create(
                access=access,
                action_id=claim.id,
                revision=access.revision,
                operation="reconcile",
                outcome=code,
            )
            self.record(
                claim,
                "community_access_outcome",
                {"binding": str(access.public_id), "code": code},
            )

        return ledger.finish(
            claim,
            self,
            status=status,
            error=code,
            write=write,
            due_in=timedelta(seconds=retry_after) if status == "queued" else None,
        )

    def begun(self, claim, access, operation, role):
        with transaction.atomic():
            self.lock_subject(claim)
            ledger.fence(claim)
            current = self.current(claim)
            if current.revision != access.revision:
                raise CommunityError("authority_changed")
            from config.backup import RESTORE_HOLD

            if AutomationPause.objects.filter(
                subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1]
            ).exists():
                raise CommunityError("restore_hold")
            if (
                operation == "grant"
                and AutomationPause.objects.filter(
                    subject_type="application", subject_id=claim.subject_id
                ).exists()
            ):
                raise CommunityError("grants_held")
            CommunityReceipt.objects.create(
                access=access,
                action_id=claim.id,
                revision=access.revision,
                operation=operation,
                role=role,
                outcome="begun",
            )
        # Appended before provider mutation; the journal names no Discord identity.
        journal.append(
            "community_effect",
            f"community:{access.public_id}",
            {"revision": access.revision, "operation": operation, "role": role.lower()},
        )

    def compensate(self, claim, access, api, user_id):
        """A stale external grant cannot be undone by DB fencing; remove and read back."""
        # No positive entitlement is created here. Restrictive cleanup uses its own
        # durable obligation; a lost lease still leaves that obligation visible.
        with transaction.atomic():
            app = Application.objects.select_for_update().get(pk=access.application_id)
            community.revoke_locked(app, force=True)
        # The protective job performs removal; never mark it complete from an
        # attempted compensation or silently swallow an unavailable provider.
        observed = read_member(api, user_id)
        return self.finish(
            claim,
            self.current(claim),
            "authority_changed_revoke_queued",
            status="uncertain",
            roles=observed["roles"] if observed else set(),
            review=True,
        )

    def run(self, claim):
        try:
            access = self.current(claim)
        except CommunityAccess.DoesNotExist:
            ledger.finish(claim, self, status="done", error="binding_absent")
            return
        if access.application.stage in TERMINAL_STAGES and not access.revoked:
            with transaction.atomic():
                app = Application.objects.select_for_update().get(
                    pk=access.application_id
                )
                community.revoke_locked(app)
            self.finish(claim, self.current(claim), "terminal_restriction_queued")
            return
        try:
            wanted = community.target(access)
        except CommunityError as exc:
            self.finish(claim, access, exc.code, status="held")
            return
        try:
            api = provider()
            if api.guild_id != access.guild_id:
                raise CommunityError("guild_mismatch")
            bound = community.identity(access)
            member = read_member(api, bound["user_id"])
            if member is None:
                self.finish(
                    claim,
                    access,
                    "absent_no_auto_join",
                    roles=set(),
                    review=bool(wanted),
                    removed=not wanted,
                )
                return
            changed_epoch = bool(wanted and member["joined_at"] != bound["joined_at"])
            protective = self.kind == community.REVOKE
            if changed_epoch and not protective:
                self.finish(
                    claim,
                    access,
                    "membership_epoch_changed",
                    status="held",
                    review=True,
                )
                return
            previous = set(access.verified_roles)
            manually_removed = bool(wanted and previous - member["roles"])
            if manually_removed and not protective:
                self.finish(
                    claim,
                    access,
                    "manual_removal_requires_review",
                    status="held",
                    review=True,
                )
                return
            current = member["roles"]
            changes = [
                ("revoke", role) for role in reversed(ROLES) if role in current - wanted
            ]
            if not protective:
                changes += [
                    ("grant", role) for role in ROLES if role in wanted - current
                ]
            for operation, role in changes:
                latest = self.current(claim)
                if latest.revision != access.revision:
                    self.compensate(claim, access, api, bound["user_id"])
                    return
                if operation == "grant":
                    try:
                        if community.desired(latest) != wanted:
                            raise CommunityError("authority_changed")
                    except CommunityError as exc:
                        self.finish(
                            claim, access, exc.code, status="held", roles=current
                        )
                        return
                self.begun(claim, access, operation, role)
                if operation == "grant":
                    grant_role(api, bound["user_id"], role)
                else:
                    revoke_role(api, bound["user_id"], role)
                observed = read_member(api, bound["user_id"])
                latest = self.current(claim)
                if operation == "grant" and (
                    latest.revision != access.revision
                    or observed is None
                    or observed["joined_at"] != bound["joined_at"]
                ):
                    self.compensate(claim, access, api, bound["user_id"])
                    return
                if observed is not None and (
                    (role in observed["roles"]) != (operation == "grant")
                ):
                    raise CommunityError("role_readback_mismatch")
                if (
                    observed is not None
                    and operation == "grant"
                    and current - observed["roles"]
                ):
                    self.finish(
                        claim,
                        access,
                        "concurrent_role_removal",
                        status="held",
                        review=True,
                        roles=observed["roles"],
                    )
                    return
                current = observed["roles"] if observed else set()
                with transaction.atomic():
                    self.lock_subject(claim)
                    ledger.fence(claim)
                    CommunityAccess.objects.filter(
                        pk=access.pk, revision=access.revision
                    ).update(verified_roles=sorted(current), updated_at=Now())
                    CommunityReceipt.objects.create(
                        access=access,
                        action_id=claim.id,
                        revision=access.revision,
                        operation=operation,
                        role=role,
                        outcome="verified",
                    )
                if observed is None:
                    break
            if current - wanted or (not protective and current != wanted):
                raise CommunityError("final_role_set_mismatch")
            code = (
                ("restrictions_verified" if protective else "roles_verified")
                if wanted
                else "roles_removed_residual_review"
            )
            self.finish(
                claim,
                access,
                code,
                roles=current,
                review=not wanted or changed_epoch or manually_removed,
                removed=not wanted and not current,
            )
        except ledger.LeaseLost:
            # If a request raced the fence, a later worker reconciles the existing
            # exact-member obligation. No completion is attributed to this lease.
            return
        except Exception as exc:
            code = exc.code if isinstance(exc, CommunityError) else "provider_unknown"
            retry = (
                max(60, exc.retry_after or 0) if isinstance(exc, CommunityError) else 60
            )
            # A retry begins with an exact-member read; it never blindly repeats
            # an accepted-but-unacknowledged role mutation. Exhaustion is visible.
            self.finish(
                claim,
                access,
                code,
                status="uncertain" if claim.final else "queued",
                review=claim.final,
                retry_after=retry,
            )


class RevokeCommunity(ReconcileCommunity):
    kind = community.REVOKE
    automated = False  # protective work must not be disabled by a subject pause
