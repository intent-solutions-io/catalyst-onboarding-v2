# Public intake (S1-T4), contact confirmation (S1-T6) and the read-only staff view (S1-T7).
from django.contrib import admin
from django.urls import include, path

from config.staff_admin import configure_site

configure_site()

urlpatterns = [
    path("staff/", admin.site.urls),
    path("", include("applications.urls")),
]
