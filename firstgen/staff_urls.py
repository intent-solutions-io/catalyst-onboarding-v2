from django.urls import path

from . import staff_views

app_name = "firstgen_staff"
urlpatterns = [
    path(
        "<uuid:public_ref>/mailbox-reconciliation/",
        staff_views.reconcile_mailbox,
        name="reconcile_mailbox",
    ),
    path(
        "<uuid:public_ref>/release/",
        staff_views.prepare_release,
        name="prepare_release",
    ),
    path(
        "<uuid:public_ref>/mailbox/",
        staff_views.confirm_mailbox,
        name="confirm_mailbox",
    ),
    path(
        "<uuid:public_ref>/signing-timers/",
        staff_views.prepare_signing_timers,
        name="prepare_signing_timers",
    ),
    path(
        "<uuid:public_ref>/envelope/", staff_views.adopt_envelope, name="adopt_envelope"
    ),
    path("<uuid:public_ref>/", staff_views.application_history, name="history"),
    path(
        "<uuid:public_ref>/review/", staff_views.prepare_review, name="prepare_review"
    ),
]
