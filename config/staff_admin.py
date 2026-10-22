"""The read-only staff view's shared admin pieces (005 S1.2 Staff; S1-T7, D-23, D-24).

Every Catalyst model admin is view-only for everyone, superusers included: add, change and delete are
refused by the admin itself, on top of the group holding only view permissions and the database role
holding only the grants services need. Staff can change no stage, history, adoption, message, agreement
or account through this interface; those arrive as named staff actions in later phases (POL-13).
"""

from django.contrib import admin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied


class ReadOnlyAdminMixin:
    actions = None

    def lookup_allowed(self, lookup, value, request=None):
        """Only the declared list filters may appear in a changelist query string. Django otherwise accepts
        a lookup on any local field, so `?idempotency_key__startswith=...` would reveal hidden values (a
        challenge id) one prefix at a time. A refused lookup is a 400 (DisallowedModelAdminLookup)."""
        declared = {f if isinstance(f, str) else f[0] if isinstance(f, tuple) else f.parameter_name
                    for f in getattr(self, "list_filter", ())}
        return lookup.split("__", 1)[0] in declared

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyModelAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    pass


class ReadOnlyTabularInline(ReadOnlyAdminMixin, admin.TabularInline):
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = False


def configure_site(site=admin.site):
    site.site_header = "Catalyst staff (read-only)"
    site.site_title = "Catalyst staff"
    site.index_title = "Applications and their history"
    site.site_url = None  # no "view site" link
    # Staff accounts and groups are managed by the owner outside the application (D-23), never here.
    if site.is_registered(Group):
        site.unregister(Group)
    # django-otp registers its device models; staff must never browse TOTP keys or recovery codes (6B.9).
    from django_otp.plugins.otp_static.models import StaticDevice
    from django_otp.plugins.otp_totp.models import TOTPDevice

    for model in (TOTPDevice, StaticDevice):
        if site.is_registered(model):
            site.unregister(model)
    # Passwords too: the owner sets them (`manage.py add_readonly_staff`, `manage.py changepassword`). The
    # admin's own form saves the whole user row, which the application role may not do.
    site.password_change = refuse_password_change
    site.password_change_done = refuse_password_change
    # 6B.9 (026 section 8, P6-D-3): the login asks for a second factor where one is required (accounts.staff_access).
    from accounts.staff_access import StaffLoginForm

    site.login_form = StaffLoginForm
    site.login_template = "otp/admin111/login.html"


def refuse_password_change(request, extra_context=None):
    raise PermissionDenied("staff passwords are set by the owner")
