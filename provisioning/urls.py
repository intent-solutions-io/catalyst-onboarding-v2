from django.urls import path

from . import views

app_name = "provisioning"
urlpatterns = [
    path("<str:token>/", views.setup, name="setup"),  # applications.links.SETUP_PATH
]
