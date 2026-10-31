"""Associate mail with an imported first-generation case (bgl.16; 034 section 3.5, "open v1 references and
Message-IDs, so replies to old threads associate").

The first generation recorded each automated message's Message-ID; the import keeps them on `ImportedRecord`
(`message_id`). A reply's In-Reply-To and References are matched exactly against them, and a subject's `[CAT-...]`
reference against the imported references. Pure lookups for the reply path: not yet called by
`correspondence.inbound` (wiring them in is follow-up work, 035 section 6), and never a basis for trusting the
sender, which stays the reply path's own check (correspondence.association, C2 and C3).
"""

import re

from .models import ImportedCase, ImportedRecord

REFERENCE = re.compile(r"\[(CAT-[A-Z0-9]{4}-[A-Z0-9]{4})\]")


def application_for_message_ids(message_ids) -> int | None:
    """The application id one of these Message-IDs belongs to, or None when none matches or they point at more than
    one application (ambiguous, as the first generation treated it)."""
    ids = [m.strip() for m in message_ids if m and m.strip()]
    if not ids:
        return None
    found = set(ImportedRecord.objects.filter(v1_table="outbound_message", message_id__in=ids,
                                              application__isnull=False).values_list("application_id", flat=True))
    return found.pop() if len(found) == 1 else None


def application_for_subject(subject: str) -> int | None:
    """The application whose first-generation reference the subject quotes, or None (none, or several)."""
    refs = set(REFERENCE.findall(subject or ""))
    found = set(ImportedCase.objects.filter(reference__in=refs).values_list("application_id", flat=True))
    return found.pop() if len(found) == 1 else None
