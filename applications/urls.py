from django.urls import path

from . import views

app_name = "applications"
urlpatterns = [
    path("request-access/", views.request_access, name="request_access"),
    path("request-access/received/", views.request_access_received, name="request_access_received"),
]
