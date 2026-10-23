"""9kg.33: staff role changes into the effect journal (029 section 6.2), so a restore never brings back access that
was removed after the backup, and the owner is told of access granted after it (accounts.restore).

Django signals on the user model and its group membership, connected in `AccountsConfig.ready()`: a created staff
account, a deactivation or reactivation, a group added or removed. Entries carry the username (the stable
identifier of a staff account; numeric ids recur after a restore) and group names: never a password hash, an
email address or a name. Creation through raw SQL (the tests' owner path) bypasses signals, as it bypasses
everything else in Django.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models.signals import m2m_changed, post_save, pre_save

from workflow import journal

KIND = "staff_role_changed"


def key(user) -> str:
    return f"staff:{user.get_username()}"


def _remember_active(sender, instance, **kwargs):
    if instance.pk is None:
        instance._journal_was_active = None
        return
    instance._journal_was_active = sender.objects.filter(pk=instance.pk).values_list("is_active", flat=True).first()


def _account_saved(sender, instance, created, **kwargs):
    if not (instance.is_staff or instance.is_superuser) and not created:
        return
    was = getattr(instance, "_journal_was_active", None)
    if created:
        change = "created"
    elif was is not None and was != instance.is_active:
        change = "reactivated" if instance.is_active else "deactivated"
    else:
        return
    journal.record(KIND, key(instance), {"change": change, "active": bool(instance.is_active), "groups": []})


def _groups_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear") or reverse:
        return
    if action == "post_clear":
        journal.record(KIND, key(instance), {"change": "group_removed", "active": bool(instance.is_active), "groups": ["*"]})
        return
    names = sorted(Group.objects.filter(pk__in=pk_set or ()).values_list("name", flat=True))
    change = "group_added" if action == "post_add" else "group_removed"
    journal.record(KIND, key(instance), {"change": change, "active": bool(instance.is_active), "groups": names})


def connect() -> None:
    User = get_user_model()
    pre_save.connect(_remember_active, sender=User, dispatch_uid="catalyst.journal.staff_pre_save")
    post_save.connect(_account_saved, sender=User, dispatch_uid="catalyst.journal.staff_post_save")
    m2m_changed.connect(_groups_changed, sender=User.groups.through, dispatch_uid="catalyst.journal.staff_groups")
