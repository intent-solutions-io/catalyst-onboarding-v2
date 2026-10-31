# Public intake (S1-T4), contact confirmation (S1-T6), the read-only staff view (S1-T7) and the permissioned
# correspondence, assessment, agreement and provisioning staff screens (P2 to P5), listed first so the admin's catch-all never shadows them.
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from agreements.views import signing_return
from config import health
from config.staff_admin import configure_site

configure_site()

urlpatterns = [
    path("healthz", health.healthz, name="healthz"),  # 6B.3: through the proxy's local socket only (HostGuard)
    path("readyz", health.readyz, name="readyz"),
    path("staff/p2/", include("correspondence.staff_urls")),
    path("staff/p3/", include("assessments.staff_urls")),
    path("staff/p4/", include("agreements.staff_urls")),
    path("staff/p5/", include("provisioning.staff_urls")),
    path("staff/", admin.site.urls),
    path("setup/", include("provisioning.urls")),  # applications.links.SETUP_PATH (P5 5B.2)
    path("withdraw/", include("provisioning.withdraw_urls")),  # applications.links.WITHDRAW_PATH (P5 5B.3)
    path("signing/return/", signing_return, name="signing_return"),  # agreements.provider.RETURN_PATH (bgl.8, 034 row 29)
    path("", include("applications.urls")),
]
# The Documenso webhook (P4 4B.2, 021 section 6): mounted only in test and development until the P6 exposure
# decision (P4-D-17).
if settings.CATALYST_ENV in ("test", "development"):
    from agreements.views import documenso_webhook

    urlpatterns.insert(0, path("hooks/documenso/", documenso_webhook, name="documenso_webhook"))

