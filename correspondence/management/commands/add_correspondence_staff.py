"""Create a staff account in one P2 role group, or add an existing account to one (016 F; D-30, D-23).

The authorized setup path, like `add_readonly_staff`: run by the owner, connected as the migration owner
role. The application role may not insert users or group memberships, so the running application can
never grant itself a P2 role. Synthetic operation only (D-30): no production staff access is authorized.
The password is read from a prompt or from the variable named by --password-env, never an argument.
"""

import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from correspondence.roles import DECISION_MAKER, OPERATOR, TEMPLATE_OWNER

ROLES = {"operator": OPERATOR, "decision-maker": DECISION_MAKER, "template-owner": TEMPLATE_OWNER}


class Command(BaseCommand):
    help = "Create a staff account in a P2 role group, or add an existing account to one (owner only)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", required=True, choices=sorted(ROLES))
        parser.add_argument("--existing", action="store_true", help="add an existing account instead of creating one")
        parser.add_argument("--password-env", help="name of an environment variable holding the password")

    def handle(self, username, role, existing=False, password_env=None, **options):
        User = get_user_model()
        group = Group.objects.filter(name=ROLES[role]).first()
        if group is None:
            raise CommandError(f"group {ROLES[role]!r} does not exist; run the migrations first")
        if existing:
            with transaction.atomic():
                user = User.objects.filter(username=username, is_superuser=False).first()
                if user is None:
                    raise CommandError(f"no non-superuser account {username!r}")
                user.groups.add(group)
            self.stdout.write(f"added {username!r} to {group.name!r}")
            return
        if password_env:
            password = os.environ.get(password_env, "")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("the passwords differ")
        user = User(username=username, is_staff=True, is_superuser=False, is_active=True)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from None
        user.set_password(password)
        with transaction.atomic():
            if User.objects.filter(username=username).exists():
                raise CommandError(f"user {username!r} already exists")
            user.save()
            user.groups.add(group)
        self.stdout.write(f"created {username!r} in {group.name!r}")
