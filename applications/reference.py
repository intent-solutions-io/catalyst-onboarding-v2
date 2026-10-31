"""The applicant-facing reference (bead bgl.5; 034 rows 6, 7 and 9, section 1.2 steps 1 and 2).

Every application carries one reference in the first generation's format, `CAT-XXXX-XXXX`: two groups of four
characters from Crockford's base32 alphabet without I, L, O and U, so it survives being read aloud or retyped. Eight
characters from a 32-letter alphabet are 40 random bits from `secrets`. It is assigned when the application is created
(the first submission), held unique by the database, never changed by the application role (no column grant, applications
migration 0010) and shown to staff on the dossier and in subjects (`with_reference`).

It is a label, never an authenticator: no applicant-facing view looks anything up by it, and nothing an applicant sends
is trusted because it quotes it (the confirmation link, a signed random id, is the only applicant credential;
applications.links). An imported first-generation application keeps the reference its applicant already holds: the
importer passes `reference=` when it creates the application, and the database refuses a duplicate. A row inserted
outside the ORM gets one from the database default, `public.catalyst_new_reference()` (applications migration 0010):
the same alphabet and length, from the 40 random bits that open a `gen_random_uuid()` (a strong random source).
"""

import re
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
GROUP = 4
ATTEMPTS = 5
# What the database accepts (the check constraint): the first generation's own operator pattern, so an imported
# reference is never refused for its letters; a reference generated here always uses ALPHABET.
STORED_PATTERN = r"^CAT-[0-9A-Z]{4}-[0-9A-Z]{4}$"
GENERATED = re.compile(rf"CAT-[{ALPHABET}]{{{GROUP}}}-[{ALPHABET}]{{{GROUP}}}")
DB_FUNCTION = "public.catalyst_new_reference"  # the same format in SQL, for a row inserted outside the ORM


class ReferenceExhausted(RuntimeError):
    """No unused reference in ATTEMPTS tries: practically impossible at 40 bits, and a failed intake, never a reuse."""


def generate() -> str:
    chars = "".join(secrets.choice(ALPHABET) for _ in range(2 * GROUP))
    return f"CAT-{chars[:GROUP]}-{chars[GROUP:]}"


def new_reference() -> str:
    """An unused reference, the model field's default. The unique constraint is the guarantee; the look-up only makes a
    collision a retry here instead of a failed submission."""
    from .models import Application

    for _ in range(ATTEMPTS):
        candidate = generate()
        if not Application.objects.filter(reference=candidate).exists():
            return candidate
    raise ReferenceExhausted("no unused application reference found")


def with_reference(subject: str, reference: str) -> str:
    """The subject a sender puts on the wire when the template version asks for it (`subject_reference`): the static
    subject, a space and the reference in brackets, as the first generation wrote it."""
    if not reference:
        raise ValueError("a subject that carries the reference needs one")
    return f"{subject} [{reference}]"
