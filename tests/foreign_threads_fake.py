"""bgl.6: a stand-in for the first-generation import's thread resolver (`firstgen.threads`, PR #153), with the same two
functions, so the association interface is tested without that app installed. Tests fill MESSAGE_IDS and REFERENCES
(application ids) and read CALLS."""

import re

MESSAGE_IDS: dict = {}
REFERENCES: dict = {}
CALLS: list = []
REFERENCE = re.compile(r"\[(CAT-[A-Z0-9]{4}-[A-Z0-9]{4})\]")


def reset() -> None:
    MESSAGE_IDS.clear()
    REFERENCES.clear()
    CALLS.clear()


def application_for_message_ids(message_ids) -> int | None:
    ids = list(message_ids)
    CALLS.append(("message_ids", ids))
    found = {MESSAGE_IDS[m] for m in ids if m in MESSAGE_IDS}
    return found.pop() if len(found) == 1 else None


def application_for_subject(subject: str) -> int | None:
    CALLS.append(("subject", subject))
    found = {REFERENCES[r] for r in REFERENCE.findall(subject or "") if r in REFERENCES}
    return found.pop() if len(found) == 1 else None
