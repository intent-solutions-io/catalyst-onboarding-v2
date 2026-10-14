"""Create a draft evidence-source version (owner-run configuration, 018 section 3.1). It approves nothing: the
owner approves the exact version on the staff screen, by its definition digest."""

from django.core.management.base import BaseCommand, CommandError

from assessments import services


class Command(BaseCommand):
    help = "Define a draft evidence source version (POL-03); approval happens on the staff screen."

    def add_arguments(self, parser):
        parser.add_argument("--key", required=True)
        parser.add_argument("--kind", required=True, choices=["work_sample_page", "credential_verification"])
        parser.add_argument("--host", required=True)
        parser.add_argument("--port", type=int, default=443)
        parser.add_argument("--path-prefix", default="/")
        parser.add_argument("--redirect-host", action="append", default=[])
        parser.add_argument("--content-type", action="append", default=[])
        parser.add_argument("--max-bytes", type=int, default=262144)
        parser.add_argument("--deadline-seconds", type=int, default=10)
        parser.add_argument("--required", action="store_true")
        parser.add_argument("--fixture-only", action="store_true")

    def handle(self, *args, **o):
        try:
            source = services.define_evidence_source(
                key=o["key"], kind=o["kind"], host=o["host"], port=o["port"], path_prefix=o["path_prefix"],
                redirect_hosts=o["redirect_host"], content_types=o["content_type"] or None, max_bytes=o["max_bytes"],
                deadline_seconds=o["deadline_seconds"], required=o["required"], fixture_only=o["fixture_only"])
        except services.Refused as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"draft {source.key} version {source.version} digest {source.definition_sha256}")
