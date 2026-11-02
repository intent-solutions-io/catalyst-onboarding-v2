"""The custody decision (POL-09, owner decision 211.7.9; council record 030 Q4, D-51 provisional): where the v2
custody copy of signed documents lives on a live host, who may retrieve it, and how its keys are recovered.

The mechanism (agreements.keystore, agreements.storage) is built. These values record D-52 Q4, ratified
2026-10-28, the delegated 2026-10-29 passphrase-escrow choice in 211.7.9, and the owner's 2026-11-02
replacement instruction. They specify the required arrangement, not proof that the operator completed it.
A missing decision still refuses live custody; activation also needs the private provisioning and owner-held
recovery receipts.
The synthetic and local environments are not live, so tests and drills store synthetic documents as before. The
owner's decision changes rows of this table (a reviewed change, like every policy constant here), never the code.

Rows:

- `location`: the custody directory, the key directory and the key mirror under the managed data root, named as the
  operator's provisioning names them (the concrete paths live in the private operations record, never here). D-51's
  provisional answer: custody under the managed data root; keys outside the application backup's rollback domain.
- `access`: who may retrieve a document. D-51 and P4-D-16: decision-makers only (the `retrieve_agreement_document`
  permission, held by the "Agreement decision-maker" group); the web process serves retrieval, nothing else does.
- `recovery_holder`: the named person who holds the wrapping key's escrow copy and performs key recovery
  (`catalyst_custody_keys --recover`). A role name here; the person is in the private record.
- `recovery_time_bound`: the stated time within which that holder restores custody reads after a key-store loss.
- `escrow`: where the wrapping key's recovery copy is kept (the estate's encrypted secret store is the proposal). The
  escrow holds the wrapping key only, never a per-document key (agreements.keystore states why).
- `provider_copy`: the treatment of the provider's own copy. Fixed by P4-D-15 until POL-10 (211.7.1) decides it; the
  claim of this module and of 9kg.34 covers v2's custody copy only.
"""

UNDECIDED = "undecided"

ROWS = (
    "location",
    "access",
    "recovery_holder",
    "recovery_time_bound",
    "escrow",
    "provider_copy",
)

DECISION = {
    "location": "managed custody volume; primary keys and live mirror in separate directories outside every archive; same-disk fallback under D-52 Q4",
    "access": "agreement decision-makers only through retrieve_agreement_document",
    "recovery_holder": "owner; no deputy during the trial",
    "recovery_time_bound": "within 24 hours; stop the worker while recovery is incomplete",
    "escrow": "wrapping key only, encrypted with an owner-held passphrase; password-manager and offline paper copies; no development-host or production-host escrow key",
    "provider_copy": "retained as the same-disk fallback recovery source; deletion only through the recorded erasure handoff under POL-10",
}

# Printed by every operator command that reports on custody, so no output overstates what the keys protect.
SCOPE = "v2_custody_copy_only: the provider's copy is outside this claim (P4-D-15) until POL-10 decides it"


def current() -> dict:
    """The decision in force: this module's DECISION (tests replace it with a decided synthetic copy)."""
    return DECISION


def problems(decision: dict | None = None) -> list[str]:
    """Every row that blocks custody in a live environment: undecided, missing, blank or unknown. Codes only."""
    decision = current() if decision is None else decision
    found = []
    for name in ROWS:
        value = decision.get(name, UNDECIDED)
        if not isinstance(value, str) or not value.strip() or value == UNDECIDED:
            found.append(f"custody.{name}:undecided")
    found += [f"custody.{name}:unknown" for name in sorted(set(decision) - set(ROWS))]
    return found
