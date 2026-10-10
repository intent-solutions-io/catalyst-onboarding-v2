# Public intake (S1-T4). Confirmation and staff views arrive in S1-T6 and S1-T7.
from django.urls import include, path

urlpatterns = [
    path("", include("applications.urls")),
]
