from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Staff accounts"

    def ready(self):
        from accounts import journal_hooks, staff_access  # noqa: F401  (connects the login-time receiver)

        journal_hooks.connect()  # 9kg.33: staff role changes into the effect journal
