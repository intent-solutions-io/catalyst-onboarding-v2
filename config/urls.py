# Public intake (S1-T4), contact confirmation (S1-T6), the read-only staff view (S1-T7) and the permissioned
# correspondence staff screens (P2 2B.4, M9), listed first so the admin's catch-all never shadows them.
from django.contrib import admin
from django.urls import include, path

from config.staff_admin import configure_site

configure_site()

urlpatterns = [
    path("staff/p2/", include("correspondence.staff_urls")),
    path("staff/p3/", include("assessments.staff_urls")),
    path("staff/", admin.site.urls),
    path("", include("applications.urls")),
]
