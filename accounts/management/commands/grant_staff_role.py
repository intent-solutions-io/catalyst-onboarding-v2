"""Grant or revoke one staff role for one account (9kg.30; 029 sections 5.2, 7 and 14; accounts.roles).

The authorized setup path, like `add_readonly_staff` and `add_correspondence_staff`: run by the owner, connected as
the migration owner role. The application role may not write users, memberships, permissions or the grant record,
so the running application can never grant itself a privilege (D-23). No raw SQL and no `manage.py shell` is part
of any staff setup step.

- A group role adds the account to (or removes it from) the group the migrations created, and only while that
  group's permissions equal the role matrix; a drifted group is refused, never silently used.
- A direct role grants (or removes) one permission on the account itself: the qualification decision and the
  provisioning approval, which no group may carry. The qualification decision is granted only while
  CATALYST_QUALIFICATION_AUTHORITY is configured (POL-05; `211.7.8` names the holders).
- A superuser is refused, as everywhere on the staff site (6B.9). Every grant and revocation writes an append-only
  `StaffRoleGrant` record naming the approval the owner cites; a no-op (already held, not held) writes nothing.

Exit 0 done, 1 refused. `--list` prints the matrix and exits.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts import grants
from accounts.models import StaffRoleGrant
from accounts.roles import DIRECT_ROLES, GROUP_ROLES, ROLES


def group_permissions(group) -> set:
    return set(group.permissions.values_list("content_type__app_label", "codename"))


class Command(BaseCommand):
    help = "Grant or revoke a staff role by name (owner only); every change is recorded append-only."

    def add_arguments(self, parser):
        parser.add_argument("username", nargs="?")
        parser.add_argument("--role", choices=sorted(ROLES))
        parser.add_argument("--revoke", action="store_true", help="remove the role instead of granting it")
        parser.add_argument("--approval-ref", help="the decision that authorizes this grant or revocation")
        parser.add_argument("--list", action="store_true", dest="list_roles", help="print the role matrix and exit")

    def handle(self, username=None, role=None, revoke=False, approval_ref=None, list_roles=False, **options):
        if list_roles:
            for slug, spec in ROLES.items():
                kind = "group " + repr(spec.group) if slug in GROUP_ROLES else "direct grant"
                self.stdout.write(f"{slug}: {kind}; {', '.join(f'{a}.{c}' for a, c in sorted(spec.expected))} ({spec.design})")
            return
        if not username or not role:
            raise CommandError("a username and --role are required (or --list)")
        approval_ref = grants.require_approval(approval_ref)
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"no account {username!r}")
        if user.is_superuser:
            raise CommandError("a superuser account holds no staff role: the owner works through manage.py")
        if not revoke and not (user.is_staff and user.is_active):
            raise CommandError("only an active staff account can be granted a role")
        with transaction.atomic():
            if role in GROUP_ROLES:
                changed, target = self._group(user, role, revoke)
            else:
                changed, target = self._direct(user, role, revoke)
            if not changed:
                self.stdout.write(f"{username!r} {'does not hold' if revoke else 'already holds'} {role!r}; nothing changed")
                return
            record = grants.record(
                user, role=role, kind=StaffRoleGrant.Kind.GROUP if role in GROUP_ROLES else StaffRoleGrant.Kind.PERMISSION,
                target=target, action=StaffRoleGrant.Action.REVOKE if revoke else StaffRoleGrant.Action.GRANT,
                approval_ref=approval_ref)
        self.stdout.write(f"{'revoked' if revoke else 'granted'} {role!r} {'from' if revoke else 'to'} {username!r} (record {record.pk})")

    def _group(self, user, role, revoke):
        spec = GROUP_ROLES[role]
        group = Group.objects.filter(name=spec.group).first()
        if group is None:
            raise CommandError(f"group {spec.group!r} does not exist; run the migrations first")
        held = group_permissions(group)
        if held != spec.expected:
            raise CommandError(f"group {spec.group!r} does not carry the role matrix (accounts.roles): "
                               f"extra {sorted(held - spec.expected)}, missing {sorted(spec.expected - held)}")
        member = user.groups.filter(pk=group.pk).exists()
        if revoke and member:
            user.groups.remove(group)
        elif not revoke and not member:
            user.groups.add(group)
        else:
            return False, group.name
        return True, group.name

    def _direct(self, user, role, revoke):
        spec = DIRECT_ROLES[role]
        if spec.needs_authority and not revoke and settings.CATALYST_QUALIFICATION_AUTHORITY != "explicit_permission":
            raise CommandError("no qualification authority is configured (CATALYST_QUALIFICATION_AUTHORITY, POL-05): "
                               "the decision role cannot be granted until the owner records it")
        permission = Permission.objects.get(content_type__app_label=spec.app_label, codename=spec.codename)
        held = user.user_permissions.filter(pk=permission.pk).exists()
        if revoke and held:
            user.user_permissions.remove(permission)
        elif not revoke and not held:
            user.user_permissions.add(permission)
        else:
            return False, f"{spec.app_label}.{spec.codename}"
        return True, f"{spec.app_label}.{spec.codename}"
