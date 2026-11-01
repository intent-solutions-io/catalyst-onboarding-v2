"""The custody leg of the restore drill (9kg.34; scripts/restore_drill.sh): synthetic only, refused outside the `test`
and `staging` environments.

    manage.py catalyst_custody_drill provision --storage-dir D --key-dir K --mirror-dir M
    manage.py catalyst_custody_drill seed    --storage-dir D --key-dir K --mirror-dir M
    manage.py catalyst_custody_drill read    --storage-dir D --key-dir K --mirror-dir M --document <public id>
    manage.py catalyst_custody_drill destroy --storage-dir D --key-dir K --mirror-dir M --document <public id>
    manage.py catalyst_custody_drill absent  --storage-dir D --key-dir K --mirror-dir M --set <backup set> --marker <m>

Staging stores no custody files (its storage setting is fixed and empty until the pilot), so the drill names the
directories on the command line and this command points the settings at them for its own run:

- `seed` makes one synthetic applicant with one stored, sealed document through the real write path
  (`agreements.storage.write`: a new data key in the key directory and its mirror, the sealed file in custody, the
  `StoredDocument` and `CustodyEnvelope` rows) and prints its public id and the document's synthetic marker;
- `read` opens a document the way retrieval does and prints `opened` with whether the plaintext hash matches the
  recorded one, or `refused` with the code (`custody_key_destroyed` after a destruction);
- `destroy` destroys the document's key with `agreements.keystore.destroy`, the step the erasure performs under the
  registry's `destroy_key` (the erasure itself refuses while the registry is undecided, so the drill calls the step);
- `journaled` says whether the journal records the document's key as destroyed, with its mac verified;
- `absent` reads every file of a backup set and reports whether any holds key material (a wrapped key file's bytes,
  a data key, the wrapping key, in raw, hex or base64 form) or the document's plaintext marker.

Output is one JSON line; the marker is synthetic. The claim is v2's custody copy only (P4-D-15 covers the provider's).
"""

import base64
import json
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.functions import Now

from agreements import custody_policy, keystore, storage
from config.guards import synthetic


class Command(BaseCommand):
    help = "The synthetic custody leg of the restore drill (9kg.34)."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=("provision", "seed", "read", "destroy", "absent", "journaled"),
        )
        parser.add_argument("--storage-dir", required=True)
        parser.add_argument("--key-dir", required=True)
        parser.add_argument("--mirror-dir", required=True)
        parser.add_argument("--document", default="")
        parser.add_argument("--set", default="")
        parser.add_argument("--marker", default="")

    def handle(
        self,
        *args,
        action,
        storage_dir,
        key_dir,
        mirror_dir,
        document,
        set,
        marker,
        **options,
    ):
        if not synthetic(getattr(settings, "CATALYST_ENV", "")):
            raise CommandError(
                "the custody drill runs only in the test and staging environments (synthetic data)"
            )
        for value in (storage_dir, key_dir, mirror_dir):
            if not Path(value).is_absolute():
                raise CommandError("the drill's directories must be absolute paths")
        settings.CATALYST_AGREEMENT_STORAGE_DIR = storage_dir
        settings.CATALYST_CUSTODY_KEY_DIR = key_dir
        settings.CATALYST_CUSTODY_KEY_MIRROR_DIR = mirror_dir
        if action == "provision":
            out = {"provisioned": keystore.provision()}
        elif action == "seed":
            out = seed()
        elif action == "absent":
            out = absent(Path(set), marker)
        elif action == "journaled":
            out = journaled(document)
        else:
            out = read(document) if action == "read" else destroy(document)
        self.stdout.write(
            json.dumps({**out, "scope": custody_policy.SCOPE}, sort_keys=True)
        )


def synthetic_document(app, pdf: bytes, *, sealed: bool = True):
    """One stored document for a synthetic applicant, through the real write path (`sealed`), or as a document stored
    in the clear before 9kg.34 was built (`sealed=False`: the plaintext file and its row, no envelope), which the
    migration then seals. Synthetic environments only."""
    from agreements.models import (
        AgreementInstance,
        AgreementTemplateVersion,
        AgreementType,
        CustodyEnvelope,
        ProviderObservation,
        StoredDocument,
    )

    if not synthetic(getattr(settings, "CATALYST_ENV", "")):
        raise CommandError(
            "synthetic documents are made only in the test and staging environments"
        )
    from agreements.template_versions import lock_type

    nda = AgreementType.objects.get(key="nda")
    with transaction.atomic():
        lock_type(nda.pk)
        instance = AgreementInstance.objects.filter(
            application=app, agreement_type=nda
        ).first()
        if instance is None:
            # A second synthetic applicant uses the current version; the drill must
            # never replace a template approval merely to exercise custody storage.
            version = AgreementTemplateVersion.objects.filter(
                agreement_type=nda, status="approved"
            ).first()
            if version is None:
                number = (
                    AgreementTemplateVersion.objects.filter(agreement_type=nda)
                    .order_by("-version")
                    .values_list("version", flat=True)
                    .first()
                    or 0
                ) + 1
                version = AgreementTemplateVersion.objects.create(
                    agreement_type=nda,
                    version=number,
                    provider_template_ref="drill",
                    provider_template_number=1,
                    pdf_sha256="0" * 64,
                )
                AgreementTemplateVersion.objects.filter(pk=version.pk).update(
                    status="approved", approved_by="custody drill", approved_at=Now()
                )
            instance = AgreementInstance.objects.create(
                application=app,
                agreement_type=nda,
                template_version=version,
                external_key=f"drill-{uuid.uuid4().hex}",
            )
    observation = ProviderObservation.objects.create(
        instance=instance, application=app, source="read", envelope_status="COMPLETED"
    )
    if sealed:
        key, digest, envelope = storage.write(pdf)
    else:
        key, digest, envelope = f"{uuid.uuid4().hex}.pdf", storage.sha256(pdf), None
        storage._write_new(key, pdf)
    item = str(
        StoredDocument.objects.filter(instance=instance).count() + 1
    )  # one document per envelope item
    stored = StoredDocument.objects.create(
        instance=instance,
        application=app,
        envelope_id="drill",
        item_id=item,
        storage_key=key,
        sha256=digest,
        size=len(pdf),
        observation=observation,
    )
    if envelope is not None:
        CustodyEnvelope.objects.create(document=stored, **envelope.fields())
    return stored


def seed() -> dict:
    from applications.models import Application

    tag = secrets.token_hex(8)
    marker = f"SYNTHETIC-CUSTODY-DRILL-{tag}"
    email = f"custody-drill-{tag}@example.test"
    app = Application.objects.create(
        email=email,
        email_key=email,
        display_name="Synthetic Custody Drill",
        stage="withdrawn",
    )
    pdf = f"%PDF-1.4\n% {marker}\n% a synthetic signed document for the custody drill\n%%EOF\n".encode()
    stored = synthetic_document(app, pdf)
    return {
        "seeded": True,
        "document": str(stored.public_id),
        "application": str(app.public_ref),
        "marker": marker,
    }


def _document(ref: str):
    from agreements.models import CustodyEnvelope, StoredDocument

    stored = (
        StoredDocument.objects.filter(public_id=ref).first()
        if len(ref or "") == 36
        else None
    )
    if stored is None:
        raise CommandError("no such document")
    return stored, CustodyEnvelope.objects.filter(document=stored).first()


def read(ref: str) -> dict:
    stored, envelope = _document(ref)
    try:
        data = storage.read(stored.storage_key, stored.sha256, stored.size, envelope)
    except storage.StorageError as exc:
        return {"read": "refused", "code": str(exc), "sealed": envelope is not None}
    return {
        "read": "opened",
        "sha256_matches": storage.sha256(data) == stored.sha256,
        "sealed": envelope is not None,
    }


def destroy(ref: str) -> dict:
    stored, envelope = _document(ref)
    if envelope is None:
        raise CommandError("the document is not sealed")
    return {
        "destroyed": keystore.destroy(
            str(stored.application.public_ref), [envelope.key_ref]
        )
    }


def absent(backup_set: Path, marker: str) -> dict:
    """Whether any file of the set holds key material or the plaintext marker. Needles: each wrapped key file's bytes,
    each present data key and the wrapping key, in raw, hex and base64 forms."""
    if not backup_set.is_absolute() or not backup_set.is_dir() or not marker:
        raise CommandError(
            "--set must be an existing absolute directory and --marker must be given"
        )
    primary, mirror = keystore.directories()
    needles = []
    secret = keystore.wrapping_key()
    raw_keys = [secret]
    for ref in sorted(keystore._listing(primary) | keystore._listing(mirror)):
        for directory in (primary, mirror):
            blob = keystore._read(directory, ref)
            if blob:
                needles.append(blob)
        try:
            raw_keys.append(keystore.load(ref))
        except keystore.KeyStoreError:
            pass
    for raw in raw_keys:
        needles += [raw, raw.hex().encode(), base64.b64encode(raw)]
    files = [p for p in backup_set.rglob("*") if p.is_file()]
    found_keys = found_marker = 0
    for path in files:
        data = path.read_bytes()
        found_keys += sum(1 for n in needles if n in data)
        found_marker += int(marker.encode() in data)
    return {
        "files": len(files),
        "needles": len(needles),
        "key_material_found": found_keys,
        "plaintext_marker_found": found_marker,
        "key_files_in_set": sum(1 for p in files if p.suffix == ".key"),
        # the sealed files the set holds: a check that read an empty or wrong directory cannot pass
        "sealed_files_in_set": sum(
            1 for p in files if p.read_bytes().startswith(keystore.MAGIC)
        ),
    }


def journaled(ref: str) -> dict:
    """Whether the journal records the document's key as destroyed, its mac verified under the erasure key."""
    from workflow import journal

    stored, envelope = _document(ref)
    if envelope is None:
        raise CommandError("the document is not sealed")
    forged = []
    secret = keystore._erasure_secret()
    refs = keystore.destroyed_refs(journal.read(), secret, forged)
    return {
        "journaled_destroyed": envelope.key_ref in refs,
        "verified": secret is not None,
        "forged": len(forged),
    }
