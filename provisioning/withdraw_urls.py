from django.urls import path

from . import views

app_name = "withdrawal"
urlpatterns = [
    path("<str:token>/", views.withdraw, name="withdraw"),  # applications.links.WITHDRAW_PATH
]
