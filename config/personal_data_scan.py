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
.localhost, example.com/net/org, matched as the domain or a subdomain of it, never as a suffix of another name), a
phone number with separators (a run id, a digest or a timestamp has none; an unseparated number is below the floor),
a street address, a fixture person's name (a receipt that carries even a synthetic applicant's name has a leak; the
list is the fixtures' names, case-insensitive, and detects no real person), a secret assignment (the keyword inside a
wider identifier or a quoted key, with a value not marked synthetic or redacted), a bearer token, a private-key block,
a long mixed-case token (judged per path segment: a digest is hex and a path or a slug is a name) and an IPv4 address
that is neither loopback, unspecified, link-local nor a documentation address (a private address names a host).
Each document is scanned line by line and again as whitespace-normalised paragraphs, so a name or number split
across a wrapped line is found and reported at the paragraph's first line. A pattern catches a class, not a person:
the positive controls in the tests plant synthetic values only.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLASSES = ("evidence", "receipt", "alert")
# The committed evidence set, as globs under the repository: every after-action report (AA-AACR), analysis evidence
# (RA-ANLY), test evidence (TQ-TEST) and decision record (AT-DECR) filed under 000-docs, the staging specification
# with its 6B records (section 16) and the launch plan with its evidence tables. A new record of one of those
# classes is scanned without a change here (tests/test_personal_data_scan.py checks the classes are covered).
EVIDENCE_PATHS = (
    "000-docs/000-aars/*.md",
    "000-docs/*-RA-ANLY-*.md",
    "000-docs/*-TQ-TEST-*.md",
    "000-docs/*-AT-DECR-*.md",
    "000-docs/026-AT-DSGN-p6-staging-deployment-specification.md",
    "000-docs/029-PP-PLAN-internal-launch-comparison-and-execution-plan.md",
)
RESERVED_DOMAINS = ("test", "example", "invalid", "localhost", "example.com", "example.net", "example.org")
# The person names the fixtures use, matched case-insensitively, and the fixtures' generic labels, matched in their
# exact case only (as prose, "a synthetic applicant" and "someone else's" are not a name). tests/test_personal_data_scan.py
# checks every name the fixtures use is on one list. A real person's name is on no list: the scan does not detect
# real names; a deny-list of invited names on the host is an owner decision, not built here.
FIXTURE_NAMES = ("Ada Example", "Ada Two", "Ada Three", "Ada Changed", "Calm Example", "Verified Example",
                 "Queued Example", "Paused Example", "Other Example", "Lost Example", "Failed Example",
                 "Expired Example", "Cancelled Example", "Grace Example", "Hedy Example", "Joan Example",  # 9kg.32
                 "Mary Example", "Opal Example", "Bea Example", "Flo Example", "Sid Example")
FIXTURE_LABELS = ("Synthetic Applicant", "Someone Else")
STREET_WORDS = ("Street", "St", "Avenue", "Ave", "Road", "Rd", "Drive", "Dr", "Lane", "Ln", "Boulevard", "Blvd",
                "Court", "Ct", "Place", "Pl", "Way", "Terrace", "Square", "Sq", "Close", "Crescent")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
# A phone number is digits in groups with separators (spaces, dots, dashes, brackets) or a leading +; ten digits
# or more in all. Run ids, digests and timestamps have no separators; dates have too few digits.
PHONE = re.compile(r"(?<![\w./-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{3,4}[ .-]\d{3,4}(?![\w-])")
STREET = re.compile(r"\b\d{1,6}\s+(?:[A-Z][A-Za-z'-]+\s+){1,4}(?:%s)\b\.?" % "|".join(STREET_WORDS))
# A secret assignment (the keyword alone, inside a wider identifier such as DB_PASSWORD, or as a quoted key such as
# "password": "..."), unless the value says it is synthetic (the estate's placeholder convention) or redacted.
# The value is taken whole (possessive) and may not continue into a call or a word, so code such as
# `lease_token = models.UUIDField(null=True)` is an assignment of an expression, not of a secret.
SECRET = re.compile(r"(?i)[\w-]*(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)[\w-]*[\"']?\s*[:=]\s*[\"']?"
                    r"(?!synthetic|redacted|\*{3})[^\s\"'<$*()]{8,}+(?![(\w])")
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
TOKEN_RUN = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{40,}(?![A-Za-z0-9+/_=-])")
HEX = re.compile(r"[0-9a-fA-F]+")
SLUG = re.compile(r"[a-z]{4,}[-_][a-z]{4,}")  # two words joined: a file name or an identifier, not a token
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.]|/\d)")


def _email(match) -> bool:
    domain = match.group(1).lower().rstrip(".")
    return not any(domain == d or domain.endswith("." + d) for d in RESERVED_DOMAINS)


def _phone(match) -> bool:
    return sum(c.isdigit() for c in match.group(0)) >= 10


def _token(match) -> bool:
    """A run is a token only if one of its path segments is on its own: forty or more characters, not hex (a
    digest), not a slug (a filed document's name) and mixed upper, lower and digits. A filesystem path is segments."""
    for segment in match.group(0).split("/"):
        if len(segment) < 40 or HEX.fullmatch(segment) or SLUG.search(segment):
            continue
        if any(c.isupper() for c in segment) and any(c.islower() for c in segment) and any(c.isdigit() for c in segment):
            return True
    return False


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
    ("fixture_name", re.compile("(?<![A-Za-z])(?:(?i:" + "|".join(re.escape(n) for n in FIXTURE_NAMES) + ")|"
                                + "|".join(re.escape(n) for n in FIXTURE_LABELS) + ")(?![A-Za-z])"), None),
    ("secret_assignment", SECRET, None),
    ("bearer_token", BEARER, None),
    ("private_key", PRIVATE_KEY, None),
    ("token", TOKEN_RUN, _token),
    ("ipv4_address", IPV4, _ipv4),
)


def _hits(line: str) -> list[str]:
    return [name for name, pattern, keep in PATTERNS if any(keep is None or keep(m) for m in pattern.finditer(line))]


def scan_text(text: str) -> list[tuple[int, str]]:
    """(line number, pattern name) for every hit, in order; a pattern is reported once per line. Each paragraph
    (lines between blank lines) is scanned again joined by single spaces, so a value split across a wrapped line is
    found and reported at the paragraph's first line, once per pattern not already found on one of its lines."""
    lines = text.splitlines()
    hits = [(number, name) for number, line in enumerate(lines, 1) for name in _hits(line)]
    start = None
    for number, line in enumerate(lines + [""], 1):
        if line.strip() and start is None:
            start = number
        elif not line.strip() and start is not None:
            found = {name for n, name in hits if start <= n < number}
            joined = " ".join(" ".join(line.split()) for line in lines[start - 1:number - 1])
            hits += [(start, name) for name in _hits(joined) if name not in found]
            start = None
    return sorted(hits)


class Unreadable(Exception):
    pass


def files(kind: str, paths: list[str]) -> list[Path]:
    """The files to scan: the given paths (a directory means its files by class suffix), or the evidence set."""
    suffixes = {"evidence": (".md",), "receipt": (".json",), "alert": None}[kind]
    found = []
    if not paths and kind == "evidence":
        for pattern in EVIDENCE_PATHS:
            matched = sorted(p for p in ROOT.glob(pattern) if p.is_file())
            if not matched:
                raise Unreadable(f"no committed evidence matches {pattern}")
            found += matched
        return found
    for raw in paths:
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
            try:
                text = sys.stdin.buffer.read().decode("utf-8")
            except UnicodeDecodeError:
                raise Unreadable("stdin is not UTF-8 text") from None  # never the bytes themselves
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
