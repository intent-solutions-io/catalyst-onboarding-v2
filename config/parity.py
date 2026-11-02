"""Production configuration for the owner-authorized replacement (D-54).

A digest-bound, read-only JSON file supplies deployment-specific non-secret values. No
profile means the existing wave-one defaults. Credentials still come from per-process
secret files; legal/template/model approvals are independently enforced by their services.
"""

import hashlib
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

STRINGS = frozenset(
    """ASSESSMENT_MODEL ASSESSMENT_PROMPT_PACK ASSESSMENT_LIVE_BASE_URL AGREEMENT_PROVIDER_URL
AGREEMENT_PROVIDER_ADDRESS AGREEMENT_PROVIDER_CA_FILE AGREEMENT_STORAGE_DIR
CUSTODY_KEY_DIR CUSTODY_KEY_MIRROR_DIR AGREEMENT_DISTRIBUTION AGREEMENT_SIGNING_BASE_URL
AGREEMENT_COUNTERSIGN AGREEMENT_COMPANY_EMAIL AGREEMENT_COMPANY_NAME AGREEMENT_COMPANY_ROLE
AGREEMENT_COUNTERSIGN_SIGNATURE RELEASE_MODE PROVISIONING_ADAPTER PROVISIONING_DOMAIN
PROVISIONING_NAMING_POLICY PROVISIONING_CREDENTIAL_MODE PROVISIONING_API_URL PROVISIONING_API_SERVER
PROVISIONING_API_ACCOUNT PROVISIONING_API_KEY_FILE PROVISIONING_IMAP_HOST
TWENTY_URL TWENTY_ADDRESS TWENTY_CA_FILE SELECTION_POLICY""".split()
)
NUMBERS = frozenset(
    """ASSESSMENT_LIVE_ACTIVATION ROUTINE_ADVANCE_ACTIVATION REPLY_INTERPRETATION_ACTIVATION
MINIMAX_REQUESTS_PER_MINUTE PROVISIONING_QUOTA_MB PROVISIONING_SEND_LIMIT""".split()
)
FLAGS = frozenset("TWENTY_PROJECTION PROVISIONING_NAMING_HOST_CHECK".split())
LISTS = frozenset(
    "PROVIDER_ALLOWED_HOSTS EVIDENCE_ALLOWED_HOSTS PROVISIONING_RESERVED_LOCAL_PARTS PROVISIONING_RESERVED_PREFIXES".split()
)
MAPPINGS = frozenset(
    "AGREEMENT_REQUIRED_DETAILS AGREEMENT_FIELD_LAYOUTS AGREEMENT_LEGACY_ENVELOPES SELECTION_POLICY_PACKS".split()
)


def enabled(settings) -> bool:
    return (
        getattr(settings, "CATALYST_ENV", "") == "production"
        and getattr(settings, "CATALYST_PARITY_ACTIVE", False) is True
    )


def automated_admission_enabled(settings) -> bool:
    """The public workflow replaces the cohort hold only under a bound production policy."""
    if (
        not enabled(settings)
        or getattr(settings, "CATALYST_ASSESSMENT_LIVE_ACTIVATION", 0) != 1
        or getattr(settings, "CATALYST_ROUTINE_ADVANCE_ACTIVATION", 0) != 2
        or not getattr(settings, "CATALYST_ASSESSMENT_MODEL", "").startswith("minimax:")
    ):
        return False
    policy = getattr(settings, "CATALYST_SELECTION_POLICY", "")
    selected = getattr(settings, "CATALYST_ASSESSMENT_PROMPT_PACK", "")
    if (
        not policy
        or not selected
        or getattr(settings, "CATALYST_SELECTION_POLICY_PACKS", {}).get(policy)
        != selected
    ):
        return False
    from assessments import pack

    try:
        return pack.load(selected).rubric.get("synthetic", True) is False
    except pack.PackRefused:
        return False


def configure(namespace, environ, read_secret):
    namespace["CATALYST_PARITY_ACTIVE"] = False
    path = environ.get("CATALYST_PARITY_CONFIG", "")
    digest = environ.get("CATALYST_PARITY_SHA256", "")
    if not path and not digest:
        return
    if (
        namespace["CATALYST_ENV"] != "production"
        or not path
        or not Path(path).is_absolute()
    ):
        raise ImproperlyConfigured(
            "parity configuration requires production and an absolute file path"
        )
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError
        value = json.loads(raw)
        if set(value) != {"decision", "settings"} or value["decision"] != "d54":
            raise ValueError
        values = value["settings"]
        if not isinstance(values, dict):
            raise ValueError
        converted = {}
        for name, item in values.items():
            if not name.startswith("CATALYST_"):
                raise ValueError
            short = name.removeprefix("CATALYST_")
            valid = (
                (short in STRINGS and isinstance(item, str))
                or (short in NUMBERS and type(item) is int and 0 <= item <= 1000000000)
                or (short in FLAGS and type(item) is bool)
                or (
                    short in LISTS
                    and isinstance(item, list)
                    and all(isinstance(x, str) for x in item)
                )
                or (short in MAPPINGS and isinstance(item, dict))
            )
            if not valid:
                raise ValueError
            converted[name] = item
    except OSError, ValueError, TypeError, KeyError, UnicodeDecodeError:
        raise ImproperlyConfigured(
            "parity configuration is unreadable, unpinned or invalid"
        ) from None
    if namespace.get("CATALYST_PROCESS_ROLE") == "fetcher" and set(converted) - {
        "CATALYST_EVIDENCE_ALLOWED_HOSTS"
    }:
        raise ImproperlyConfigured(
            "the fetcher profile may configure only evidence hosts"
        )
    bindings = converted.get("CATALYST_AGREEMENT_LEGACY_ENVELOPES", {})
    keys = set()
    for envelope, binding in bindings.items():
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", envelope)
            or not isinstance(binding, dict)
            or set(binding) != {"external_key", "company_email", "company_role"}
            or not isinstance(binding["external_key"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", binding["external_key"])
            or binding["external_key"].startswith("ag_")
            or binding["external_key"] in keys
            or binding["company_role"] not in ("SIGNER", "APPROVER")
            or not isinstance(binding["company_email"], str)
            or not re.fullmatch(r"[^\s@]+@[^\s@]+", binding["company_email"])
        ):
            raise ImproperlyConfigured("legacy signing handover binding is invalid")
        keys.add(binding["external_key"])
    namespace.update(converted)
    namespace["CATALYST_AGREEMENT_PROVIDER_TOKEN"] = read_secret(
        "CATALYST_AGREEMENT_PROVIDER_TOKEN", ""
    )
    namespace["CATALYST_AGREEMENT_LEGACY_TOKEN"] = read_secret(
        "CATALYST_AGREEMENT_LEGACY_TOKEN", ""
    )
    namespace["CATALYST_PARITY_ACTIVE"] = True


def endpoint_problems(settings, name, *, pinned="", trust="", origin=False):
    url = getattr(settings, name, "")
    if not url:
        return []
    problems = []
    try:
        parts = urlsplit(url)
        hosts = getattr(settings, "CATALYST_PROVIDER_ALLOWED_HOSTS", ())
        valid = (
            parts.scheme == "https"
            and parts.hostname in hosts
            and parts.port in (None, 443)
            and not parts.username
            and not parts.password
            and not parts.query
            and not parts.fragment
            and not parts.hostname.endswith((".test", ".invalid", ".localhost"))
            and (not origin or parts.path in ("", "/"))
        )
    except ValueError, TypeError, AttributeError:
        valid = False
    if not valid:
        problems.append(
            f"{name} must be HTTPS on an explicitly allowed production host"
        )
    if pinned:
        try:
            address = ipaddress.ip_address(getattr(settings, pinned, ""))
            if not address.is_global:
                raise ValueError
        except ValueError:
            problems.append(f"{pinned} must pin a public unicast provider address")
    if trust and not Path(getattr(settings, trust, "")).is_absolute():
        problems.append(f"{trust} must name an absolute verifying CA bundle")
    return problems


def provisioning_problems(settings):
    problems = endpoint_problems(settings, "CATALYST_PROVISIONING_API_URL", origin=True)
    adapter = getattr(settings, "CATALYST_PROVISIONING_ADAPTER", "")
    if adapter and adapter != "provisioning.mxroute.MXrouteHost":
        problems.append(
            "production provisioning must use provisioning.mxroute.MXrouteHost"
        )
    if not adapter:
        return problems
    if getattr(settings, "CATALYST_PROVISIONING_DOMAIN", "") != "intentsolutions.io":
        problems.append("production provisioning must use the approved company domain")
    for name in (
        "CATALYST_PROVISIONING_API_URL",
        "CATALYST_PROVISIONING_API_SERVER",
        "CATALYST_PROVISIONING_API_ACCOUNT",
    ):
        if not getattr(settings, name, ""):
            problems.append(f"{name} is required for production provisioning")
    if not str(getattr(settings, "CATALYST_PROVISIONING_API_KEY_FILE", "")).startswith(
        "/run/secrets/"
    ):
        problems.append("the provisioning API key must be a per-process secret file")
    if getattr(settings, "CATALYST_PROVISIONING_IMAP_HOST", "") not in getattr(
        settings, "CATALYST_MAIL_ALLOWED_HOSTS", ()
    ):
        problems.append("the provisioning IMAP host must be the approved mail host")
    return problems


def process_problems(settings, kind):
    if not enabled(settings):
        return []
    role = getattr(settings, "CATALYST_PROCESS_ROLE", "")
    if (
        kind != "web"
        and role not in ("web", "fetcher", "reconcile", "backup")
        and kind != "reconcile"
    ):
        return []
    return [
        f"{name} may be held only by the worker or owner-run provider commands"
        for name in (
            "CATALYST_AGREEMENT_PROVIDER_TOKEN",
            "CATALYST_AGREEMENT_LEGACY_TOKEN",
            "CATALYST_ASSESSMENT_API_KEY",
            "CATALYST_TWENTY_TOKEN",
        )
        if getattr(settings, name, "")
    ]
