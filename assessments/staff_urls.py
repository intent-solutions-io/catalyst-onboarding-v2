"""URLs of the P3 evidence staff screens (018; task 3B.1), mounted at /staff/p3/ before the read-only admin."""

from django.urls import path

from . import staff_views as v
from .scorecard_views import selection_report

app_name = "assessments_staff"
urlpatterns = [
    path("selection-report/", selection_report, name="selection_report"),
    path("sources/", v.source_list, name="sources"),
    path("sources/<int:pk>/", v.source_detail, name="source"),
    path("sources/<int:pk>/approve/", v.approve_source, name="approve_source"),
    path("applications/<uuid:public_ref>/evidence/", v.evidence, name="evidence"),
    path("applications/<uuid:public_ref>/evidence/proceed/", v.proceed, name="proceed"),
    path("applications/<uuid:public_ref>/assessment/rerun/", v.rerun, name="rerun"),
    path("applications/<uuid:public_ref>/questions/author/", v.author, name="author"),
    path("applications/<uuid:public_ref>/decision/", v.decision, name="decision"),
    path("applications/<uuid:public_ref>/decision/record/", v.decide, name="decide"),
    path("items/<uuid:public_id>/refetch/", v.refetch, name="refetch"),
]
