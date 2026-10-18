"""URLs of the P5 provisioning staff screen (023 sections 7 and 9; 5B.3b), mounted at /staff/p5/ before the read-only
admin."""

from django.urls import path

from . import staff_views as v

app_name = "provisioning_staff"
urlpatterns = [
    path("applications/<uuid:public_ref>/provisioning/", v.provisioning, name="provisioning"),
    path("applications/<uuid:public_ref>/provisioning/act/", v.act, name="act"),
]
