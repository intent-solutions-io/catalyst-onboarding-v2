"""The personal-data scan over evidence (9kg.40; TEST-P6-35; 026 section 11.2).

No artifact the repository or the host keeps as evidence may carry personal data: not the committed records (the
after-action reports and the evidence documents), not a backup or restore-drill receipt, not an alert, not the
deployment receipt. gitleaks finds credentials; this finds the rest, and it is run

- in CI, over the committed evidence, by tests/test_personal_data_scan.py (the full suite is the CI gate);
- by the host's receipt step, deploy/staging/adapters/receipt.sh, over the deployment receipt it has just written
  and the pre-deploy backup's receipt, before either counts: a hit withholds the receipt and fails the step.

Standard library only, so the host runs it with its python3 and no Django:

    python3 -m config.personal_data_scan --class evidence            # the committed evidence set (EVIDENCE_PATHS)
    python3 -m config.personal_data_scan --class receipt PATH...     # receipt files, or directories of *.json
    python3 -m config.personal_data_scan --class alert PATH...|-     # alert text (a log, or stdin)

Output: one line per hit, "path:line: pattern" (the location and the pattern's name, never the matched value, so
the report itself leaks nothing), then a count on stderr. Exit 0 clean, 1 a hit, 2 nothing scanned or an input that
could not be read (fail closed: an empty result is meaningful only when something was read).

Patterns: an email address outside the reserved example domains (RFC 2606 and 6761: .test, .example, .invalid,
.localhost, example.com/net/org), a phone number with separators (a run id, a digest or a timestamp has none), a street
address, a fixture person's name (a receipt that carries even a synthetic applicant's name has a leak), a secret
assignment, a bearer token, a private-key block, a long mixed-case token (a digest is hex and is allowed) and an IPv4
address that is neither loopback, unspecified, link-local nor a documentation address (a private address names a
host). A pattern catches a class, not a person: the positive controls in the tests plant synthetic values only.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLASSES = ("evidence", "receipt", "alert")
# The committed evidence set: the after-action reports, the compatibility and first-slice evidence, the staging
# specification with its 6B records (section 16) and the launch plan with its evidence tables.
EVIDENCE_PATHS = (
    "000-docs/000-aars",
    "000-docs/012-RA-ANLY-s1-t1-compatibility-evidence.md",
    "000-docs/013-TQ-TEST-first-slice-acceptance-evidence.md",
    "000-docs/026-AT-DSGN-p6-staging-deployment-specification.md",
    "000-docs/029-PP-PLAN-internal-launch-comparison-and-execution-plan.md",
)
RESERVED_DOMAINS = (".test", ".example", ".invalid", ".localhost", "example.com", "example.net", "example.org")
# The person names the fixtures use (tests/test_personal_data_scan.py checks the fixtures stay within this list).
FIXTURE_NAMES = ("Ada Example",)
STREET_WORDS = ("Street", "St", "Avenue", "Ave", "Road", "Rd", "Drive", "Dr", "Lane", "Ln", "Boulevard", "Blvd",
                "Court", "Ct", "Place", "Pl", "Way", "Terrace", "Square", "Sq", "Close", "Crescent")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
# A phone number is digits in groups with separators (spaces, dots, dashes, brackets) or a leading +; ten digits
# or more in all. Run ids, digests and timestamps have no separators; dates have too few digits.
PHONE = re.compile(r"(?<![\w./-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{2,4})[ .-]\d{3,4}[ .-]\d{3,4}(?![\w-])")
STREET = re.compile(r"\b\d{1,6}\s+(?:[A-Z][A-Za-z'-]+\s+){1,4}(?:%s)\b\.?" % "|".join(STREET_WORDS))
# A secret assignment, unless the value says it is synthetic (the estate's placeholder convention) or redacted.
SECRET = re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)\b\s*[:=]\s*[\"']?"
                    r"(?!synthetic|redacted|\*{3})[^\s\"'<$*]{8,}")
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
TOKEN_RUN = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{40,}(?![A-Za-z0-9+/_=-])")
HEX = re.compile(r"[0-9a-fA-F]+")
SLUG = re.compile(r"[a-z]{4,}[-_][a-z]{4,}")  # two words joined: a file name or an identifier, not a token
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.]|/\d)")


def _email(match) -> bool:
    domain = match.group(1).lower().rstrip(".")
    return not any(domain == d.lstrip(".") or domain.endswith(d) for d in RESERVED_DOMAINS)


def _phone(match) -> bool:
    return sum(c.isdigit() for c in match.group(0)) >= 10


def _token(match) -> bool:
    value = match.group(0)
    if HEX.fullmatch(value) or SLUG.search(value):
        return False  # a digest, or a slug such as a filed document's name
    return any(c.isupper() for c in value) and any(c.islower() for c in value) and any(c.isdigit() for c in value)


def _ipv4(match) -> bool:
    try:
        address = ipaddress.IPv4Address(match.group(0))
    except ValueError:
        return False
    documentation = any(address in ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
    return not (address.is_loopback or address.is_unspecified or address.is_link_local or documentation
                or address == ipaddress.IPv4Address("255.255.255.255"))


PATTERNS = (
    ("email", EMAIL, _email),
    ("phone", PHONE, _phone),
    ("street_address", STREET, None),
    ("fixture_name", re.compile("|".join(re.escape(n) for n in FIXTURE_NAMES)), None),
    ("secret_assignment", SECRET, None),
    ("bearer_token", BEARER, None),
    ("private_key", PRIVATE_KEY, None),
    ("token", TOKEN_RUN, _token),
    ("ipv4_address", IPV4, _ipv4),
)


def scan_text(text: str) -> list[tuple[int, str]]:
    """(line number, pattern name) for every hit, in order; a pattern is reported once per line."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern, keep in PATTERNS:
            if any(keep is None or keep(m) for m in pattern.finditer(line)):
                hits.append((number, name))
    return hits


class Unreadable(Exception):
    pass


def files(kind: str, paths: list[str]) -> list[Path]:
    """The files to scan: the given paths (a directory means its files by class suffix), or the evidence set."""
    suffixes = {"evidence": (".md",), "receipt": (".json",), "alert": None}[kind]
    found = []
    for raw in paths or (EVIDENCE_PATHS if kind == "evidence" else ()):
        path = Path(raw) if Path(raw).is_absolute() or kind != "evidence" else ROOT / raw
        if path.is_dir():
            found += sorted(p for p in path.rglob("*") if p.is_file() and (suffixes is None or p.suffix in suffixes))
        elif path.is_file():
            found.append(path)
        else:
            raise Unreadable(f"not a file or directory: {raw}")
    return found


def scan_files(kind: str, paths: list[str]) -> tuple[list[str], int, int]:
    """(hit lines, files scanned, lines scanned). Raises Unreadable for a missing path or undecodable content."""
    hits, scanned_files, scanned_lines = [], 0, 0
    for path in files(kind, paths):
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise Unreadable(f"cannot read {path}: {exc.__class__.__name__}") from exc
        scanned_files += 1
        scanned_lines += text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        hits += [f"{shown}:{number}: {name}" for number, name in scan_text(text)]
    return hits, scanned_files, scanned_lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan evidence, receipts or alert text for personal data.")
    parser.add_argument("--class", dest="kind", choices=CLASSES, required=True)
    parser.add_argument("paths", nargs="*", help="files or directories; '-' reads alert text from stdin")
    args = parser.parse_args(argv)
    try:
        if args.paths == ["-"]:
            if args.kind != "alert":
                raise Unreadable("stdin is for alert text only")
            text = sys.stdin.buffer.read().decode("utf-8")
            hits = [f"stdin:{number}: {name}" for number, name in scan_text(text)]
            scanned_files, scanned_lines = 1, text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        else:
            hits, scanned_files, scanned_lines = scan_files(args.kind, args.paths)
    except (UnicodeDecodeError, Unreadable) as exc:
        print(f"personal-data scan: unreadable input: {exc}", file=sys.stderr)
        return 2
    if scanned_files == 0 or scanned_lines == 0:
        print("personal-data scan: nothing scanned; refusing to report clean", file=sys.stderr)
        return 2
    for hit in hits:
        print(hit)
    print(f"personal-data scan ({args.kind}): {scanned_files} files, {scanned_lines} lines, {len(hits)} hits",
          file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
