from django.urls import path

from . import staff_views

app_name = "firstgen_staff"
urlpatterns = [
    path(
        "<uuid:public_ref>/envelope/", staff_views.adopt_envelope, name="adopt_envelope"
    ),
    path("<uuid:public_ref>/", staff_views.application_history, name="history"),
    path(
        "<uuid:public_ref>/review/", staff_views.prepare_review, name="prepare_review"
    ),
]
