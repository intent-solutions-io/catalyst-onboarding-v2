from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Staff accounts"

    def ready(self):
        from accounts import staff_access  # noqa: F401  (connects the login-time receiver)
