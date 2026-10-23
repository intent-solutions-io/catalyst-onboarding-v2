"""URLs of the P4 agreement staff screen (021 section 9; 4B.3), mounted at /staff/p4/ before the read-only admin."""

from django.urls import path

from . import staff_views as v

app_name = "agreements_staff"
urlpatterns = [
    path("applications/<uuid:public_ref>/agreements/", v.agreements, name="agreements"),
    path("applications/<uuid:public_ref>/agreements/act/", v.act, name="act"),
    path("documents/<uuid:public_id>/retrieve/", v.retrieve, name="retrieve"),
    path("templates/", v.template_list, name="templates"),  # 9kg.47
    path("templates/<int:pk>/approve/", v.approve_template, name="approve_template"),
]
