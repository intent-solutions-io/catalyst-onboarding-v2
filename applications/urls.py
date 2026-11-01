from django.urls import path

from . import views
from .brand_assets import ASSETS, partner_asset

app_name = "applications"
urlpatterns = [
    *[
        path(f"request-access/assets/{name}", partner_asset, {"name": name})
        for name in ASSETS
    ],
    path("request-access/", views.request_access, name="request_access"),
    path(
        "request-access/received/",
        views.request_access_received,
        name="request_access_received",
    ),
    # bgl.2 (034 row 1): the first generation's exact public paths, which every link in the wild uses. Distinct routes,
    # not redirects, so no APPEND_SLASH hop and no loop; a POST to either form is answered on the same form.
    path("request-access", views.request_access, name="request_access_exact"),
    path(
        "request-access/received",
        views.request_access_received,
        name="request_access_received_exact",
    ),
    path("confirm/<str:token>/", views.confirm, name="confirm"),  # links.CONFIRM_PATH
]
