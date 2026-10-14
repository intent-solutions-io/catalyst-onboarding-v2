"""The frozen snapshot of a run and the minimized request built from it (018 5.1, 5.2; P3-D-6). Synthetic only.

`manifest` names exactly what a run may see: the adopted version (with a digest of its claims), the latest slot
of every claim with its status, the capture of each fetched slot (with the digest of its derivative), the pack,
rubric and schema versions. Its digest (`snapshot_sha256`) binds the run, the budgets and, later, the decision;
anything that changes it (a re-fetch, a new adoption, a new pack) makes a new snapshot.

`build_request` renders what may leave Catalyst: run-local aliases instead of names and identifiers; the claims
with email addresses, phone numbers and links replaced and the applicant's name replaced by "the applicant";
each capture's derivative, scrubbed the same way, capped, and fenced as data with a per-run nonce; and the
missing evidence by status only. `names_applicant` is computed locally and sent as a yes or no; the name itself
never leaves. Contact details, tokens, staff notes, correspondence and other applicants are never read here.
"""

import hashlib
import json
import re
import secrets
import unicodedata
from dataclasses import dataclass, field

from . import fetch
from .models import EvidenceItem

ITEM_CHARS, MAX_ITEMS, TOTAL_CHARS, CLAIM_CHARS = 8_000, 12, 40_000, 2_000
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
_PHONE = re.compile(r"\+?\d[\d ()./-]{6,}\d")


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _latest_items(application, version):
    latest = {}
    for item in (EvidenceItem.objects.filter(application=application, adopted_version=version)
                 .select_related("source").prefetch_related("captures").order_by("claim_ref", "round")):
        latest[item.claim_ref] = item
    return [latest[k] for k in sorted(latest)]


def manifest(application, pack) -> dict | None:
    adoption = application.adoptions.select_related("submission_version").first()
    if adoption is None:
        return None
    version = adoption.submission_version
    claims = (version.submitted_fields or {}).get("claims") or {}
    entries = []
    for item in _latest_items(application, version):
        capture = item.captures.order_by("-attempt_number").first() if item.status == "fetched" else None
        entries.append({"claim": item.claim_ref, "item": str(item.public_id), "status": item.status,
                        "reason": item.reason_code,
                        "capture": capture.pk if capture else None,
                        "derived_sha256": capture.derived_sha256 if capture else "",
                        "outcome": capture.outcome if capture else ""})
    from .schema import SCHEMA_VERSION

    return {"version": str(version.public_id), "claims_sha256": _sha(claims), "items": entries,
            "pack": pack.name, "pack_sha256": pack.sha256, "rubric_version": pack.rubric_version,
            "schema_version": SCHEMA_VERSION}


def snapshot_sha256(value: dict) -> str:
    return _sha(value)


@dataclass
class SentItem:
    alias: str
    claim: str
    text: str
    truncated: bool
    names_applicant: bool
    markers: list = field(default_factory=list)
    marker_spans: list = field(default_factory=list)


@dataclass
class Request:
    system: str
    prompt: str
    criteria: list
    items: dict
    nonce: str
    sha256: str


def _names(application) -> list:
    name = unicodedata.normalize("NFKC", application.display_name or "").strip()
    parts = [p for p in re.split(r"\s+", name) if len(p) >= 3]
    return sorted({name, *parts} - {""}, key=len, reverse=True)


def scrub(text: str, names: list) -> str:
    text = _EMAIL.sub("[email removed]", text)
    text = _URL.sub("[link removed]", text)
    text = _PHONE.sub("[number removed]", text)
    for name in names:
        text = re.sub(re.escape(name), "the applicant", text, flags=re.I)
    return text


def _fence(text: str) -> str:
    return text.replace("<<", "‹‹").replace(">>", "››")  # a delimiter look-alike can never close a block


def build_request(application, value: dict, pack) -> Request:
    from .models import EvidenceCapture

    names = _names(application)
    version = application.versions.get(public_id=value["version"])
    claims = (version.submitted_fields or {}).get("claims") or {}
    nonce = secrets.token_hex(8)
    items, missing, total = {}, [], 0
    for entry in value["items"]:
        if entry["capture"] is None or entry["outcome"] == "not_found":
            missing.append(f"- {entry['claim']}: {entry['status']}{' (' + entry['outcome'] + ')' if entry['outcome'] else ''}")
            continue
        if len(items) >= MAX_ITEMS:
            missing.append(f"- {entry['claim']}: not sent (item limit)")
            continue
        capture = EvidenceCapture.objects.get(pk=entry["capture"])
        raw = capture.derived_text
        folded = raw.casefold()
        names_applicant = any(n.casefold() in folded for n in names)
        text = _fence(scrub(raw, names))
        truncated = capture.truncated
        budget = min(ITEM_CHARS, TOTAL_CHARS - total)
        if len(text) > budget:
            text, truncated = text[:max(budget, 0)], True
        total += len(text)
        alias = f"E{len(items) + 1}"
        spans = sorted({m.group(0) for _, pattern in fetch._MARKERS for m in pattern.finditer(text)})
        items[alias] = SentItem(alias, entry["claim"], text, truncated, names_applicant, list(capture.injection_markers), spans)
    lines = [f"RUBRIC (version {pack.rubric_version}):"]
    lines += [f"- {c['id']}{' (required)' if c.get('required') else ''}: {c['definition']}" for c in pack.criteria]
    lines.append("\nAPPLICANT CLAIMS (unverified statements):")
    for i, work in enumerate(claims.get("work") or [], start=1):
        lines.append(f"- work sample {i}: {_fence(scrub(work.get('note') or '', names))[:200]}")
    for key, label in (("contribution", "what the applicant says they personally did"), ("experience", "experience"),
                       ("confidential_description", "private or confidential work (described)")):
        if claims.get(key):
            lines.append(f"- {label}: {_fence(scrub(claims[key], names))[:CLAIM_CHARS]}")
    for i, credential in enumerate(claims.get("credentials") or [], start=1):
        lines.append(f"- credential {i}: {_fence(scrub(credential.get('name') or '', names))[:200]}"
                     f", issuer {_fence(scrub(credential.get('issuer') or '', names))[:200]}")
    lines.append("\nEVIDENCE ITEMS:")
    for item in items.values():
        lines.append(f"{item.alias} ({item.claim}; names the applicant: {'yes' if item.names_applicant else 'no'};"
                     f" truncated: {'yes' if item.truncated else 'no'})")
        lines.append(f"<<DATA alias={item.alias} nonce={nonce}>>\n{item.text}\n<</DATA nonce={nonce}>>")
    if missing:
        lines.append("\nMISSING EVIDENCE (never evidence against the applicant):")
        lines += missing
    prompt = "\n".join(lines)
    digest = hashlib.sha256((pack.system + "\n\n" + prompt).encode()).hexdigest()
    return Request(pack.system, prompt, pack.criteria, items, nonce, digest)
