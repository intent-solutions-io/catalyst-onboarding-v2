from django.urls import path

from . import staff_views

app_name = "firstgen_staff"
urlpatterns = [path("<uuid:public_ref>/", staff_views.application_history, name="history")]
