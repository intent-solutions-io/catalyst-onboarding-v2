"""Create an individual staff account in the read-only staff group (S1-T7; D-23, POL-13 PROPOSED).

The authorized setup path: run by the owner, connected as the migration owner role. The application role
cannot run it, because it may not insert users or group memberships (accounts migrations 0002 and 0003),
so the running application can never create or promote staff. The account is staff but never a
superuser. The password is read from a prompt, or from the variable named by --password-env for a
non-interactive run; it is never taken as an argument, so it never appears in a process list.
"""

import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

READ_ONLY_STAFF = "Read-only staff"


class Command(BaseCommand):
    help = "Create a staff account in the read-only staff group (owner only)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password-env", help="name of an environment variable holding the password")

    def handle(self, username, password_env=None, **options):
        if password_env:
            password = os.environ.get(password_env, "")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("the passwords differ")
        User = get_user_model()
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
            user.groups.add(Group.objects.get(name=READ_ONLY_STAFF))
        self.stdout.write(f"created read-only staff account {username!r}")
