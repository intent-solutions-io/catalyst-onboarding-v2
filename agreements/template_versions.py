"""Select the current approved template, serialized with replacement when issuing an agreement."""

from django.db import connection

from .models import AgreementTemplateVersion, AgreementType


def lock_type(type_id):
    if not connection.in_atomic_block:
        raise RuntimeError("template lock requires a transaction")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"catalyst.agreement-template:{type_id}"],
        )


def approved_version(
    type_key: str, *, for_update=False
) -> AgreementTemplateVersion | None:
    if for_update:
        type_id = (
            AgreementType.objects.filter(key=type_key)
            .values_list("pk", flat=True)
            .first()
        )
        if type_id is None:
            return None
        lock_type(type_id)
    return (
        AgreementTemplateVersion.objects.select_related("agreement_type")
        .filter(
            agreement_type__key=type_key,
            status=AgreementTemplateVersion.Status.APPROVED,
        )
        .order_by("-version")
        .first()
    )
