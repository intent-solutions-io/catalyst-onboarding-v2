"""9kg.33: replay journaled staff role changes against a restored database (config.post_restore).

The rule is least privilege. Access removed after the backup (a deactivation, a group removed) is removed again
from the restored rows. Access granted after the backup (an account created, a group added, a reactivation) is
never granted from a file: it opens one `restore_effect_staff_account` item per account for the owner, who
re-issues it through the authorized commands. Accounts are named by the journal's opaque reference, resolved
against the restored roster. Every entry is idempotent: a second replay finds the restored rows already as the
journal says, or the item already open, and changes nothing. A `prepare` entry (a removal journaled before its
commit) is replayed like a done one.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from workflow import journal

ITEM = "restore_effect_staff_account"


def replay(entries, opener) -> dict:
    User = get_user_model()
    report = {"replayed": 0, "reflected": 0, "items": 0, "target_missing": 0}
    by_ref = {journal.staff_ref(u.get_username()): u for u in User.objects.all()}
    for entry in entries:
        change, groups = entry.data.get("change"), entry.data.get("groups") or []
        user = by_ref.get(entry.key)
        if change in ("created", "reactivated", "group_added") or user is None:
            if user is None and change not in ("created",):
                report["target_missing"] += 1
            # Grants are the owner's act, never a replay's: one item per account, whatever the entry.
            if opener(ITEM, entry.key):
                report["items"] += 1
            continue
        if change == "deactivated":
            if user.is_active:
                User.objects.filter(pk=user.pk).update(is_active=False)
                user.is_active = False
                report["replayed"] += 1
            else:
                report["reflected"] += 1
        elif change == "group_removed":
            removed = user.groups.all() if groups == ["*"] else user.groups.filter(name__in=groups)
            names = list(removed.values_list("name", flat=True))
            if names:
                user.groups.remove(*Group.objects.filter(name__in=names))
                report["replayed"] += 1
            else:
                report["reflected"] += 1
    return report
