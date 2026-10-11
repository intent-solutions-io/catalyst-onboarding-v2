# Public intake (S1-T4) and contact confirmation (S1-T6). Staff views arrive in S1-T7.
from django.urls import include, path

urlpatterns = [
    path("", include("applications.urls")),
]
