"""The applicant identity key (005 S1.3; POL-01 PROPOSED default, owner may change it).

The key is the whole address, trimmed, Unicode-normalized (NFKC) and case-folded, with an
internationalized domain converted to its ASCII (IDNA) form. Plus-addressing is not folded, so
`ada+x@example.test` and `ada@example.test` are different identities. The address as typed is kept
separately for sending.
"""

import unicodedata


def email_key(address: str) -> str:
    normalized = unicodedata.normalize("NFKC", address.strip()).casefold()
    local, sep, domain = normalized.rpartition("@")
    if not sep or not local or not domain:
        raise ValueError("not an email address")
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("the domain cannot be converted to its ASCII form") from exc
    return f"{local}@{ascii_domain}"
