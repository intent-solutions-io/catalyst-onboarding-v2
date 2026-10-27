"""9kg.31.11: the Django mail backend for production until Django's own mails have a live path (9kg.77).

Three applicant mails are sent through Django's mailer: the contact confirmation (correspondence.verification), the
password setup (provisioning.credentials) and the withdrawal link (provisioning.closure). In production a file sink
would keep their live bearer links and addresses on disk and let each sender record a delivery that never happened;
this backend refuses every message instead, so each sender takes its failure path (a retried then failed send, an
uncertain setup that reopens, a staff item for the withdrawal) and nothing is written anywhere.
"""

from django.core.mail.backends.base import BaseEmailBackend


class MailRefused(Exception):
    """Django's mailer has no live path in this environment (9kg.77)."""


class RefusingEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        raise MailRefused("django_mail_has_no_live_path")
