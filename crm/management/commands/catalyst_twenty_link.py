"""Pin one application to the Twenty person staff confirmed, and queue its projection (bgl.14; the first generation's
`crm link`). Used after a `twenty_ambiguous_match`, `twenty_person_linked_elsewhere` or `twenty_linked_person_missing`
staff item; the item is then acknowledged on the staff screen.

    manage.py catalyst_twenty_link --application <public reference> --person <Twenty person id>
"""

from django.core.management.base import BaseCommand, CommandError

from applications.models import Application
from crm.projection import link_person


class Command(BaseCommand):
    help = "Link an application to a Twenty person and queue its projection."

    def add_arguments(self, parser):
        parser.add_argument("--application", required=True, help="the application's public reference")
        parser.add_argument("--person", required=True, help="the Twenty person id")

    def handle(self, *args, application, person, **options):
        found = Application.objects.filter(public_ref=application).first()
        if found is None:
            raise CommandError("no such application")
        try:
            link_person(found, person)
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write("linked; projection queued")
