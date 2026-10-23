"""9kg.33: replay journaled staff role changes against a restored database (config.post_restore).

The rule is least privilege. Access removed after the backup (a deactivation, a group removed) is removed again
from the restored rows. Access granted after the backup (an account created, a group added, a reactivation) is
never granted from a file: it opens one `restore_effect_staff_account` item per account for the owner, who
re-issues it through the authorized commands. Every entry is idempotent: a second replay finds the restored rows
already as the journal says, or the item already open, and changes nothing.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from correspondence.staff_items import open_item

ITEM = "restore_effect_staff_account"


def replay(entries) -> dict:
    User = get_user_model()
    report = {"replayed": 0, "reflected": 0, "items": 0}
    for entry in entries:
        username = entry.key.removeprefix("staff:")
        change, groups = entry.data.get("change"), entry.data.get("groups") or []
        user = User.objects.filter(username=username).first()
        if change in ("created", "reactivated", "group_added") or user is None:
            # Grants are the owner's act, never a replay's: one item per account, whatever the entry.
            open_item(ITEM, f"staff:{username}", audit=False)
            report["items"] += 1
            continue
        if change == "deactivated":
            if user.is_active:
                User.objects.filter(pk=user.pk).update(is_active=False)
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
