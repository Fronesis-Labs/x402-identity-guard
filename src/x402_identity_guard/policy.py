"""Reference policy: turns a TRC-8004 AgentRecord into an identity & trust decision.

Updates the evaluation chain to use AgentIdentity invariants, TrustSignals,
and semantic classifications (such as KNOWN_BUT_UNTRUSTED).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry_client import (
    AgentClassification,
    AgentRecord,
    RegistryClient,
    RegistryError,
)

Status = Literal["ALLOW", "FLAG", "DENY"]

# Threshold constants for policy decisions
MIN_REPUTATION_SCORE = 50.0  # Average value threshold (0-100 style)
MAX_NEGATIVE_VALIDATIONS = 0 # Any rejected/negative validation blocks execution


@dataclass
class Decision:
    status: Status
    reason: str
    agent_id: str
    record: AgentRecord | None = None


def _decide(record: AgentRecord) -> Decision:
    identity = record.identity
    signals = record.trust_signals

    # 1. Non-existent identity
    if not identity.exists or record.classification == AgentClassification.NOT_FOUND:
        return Decision("DENY", "no_identity", identity.agent_id, record)

    # 2. Cryptographic / Invariant check (owner == wallet == metadata_wallet)
    if not identity.is_consistent:
        return Decision("DENY", "inconsistent_identity", identity.agent_id, record)

    # 3. Validation checks (if total validations exist, ensure positive validations match)
    pos_val, total_val = signals.validation_summary
    if total_val > 0 and pos_val < total_val:
        return Decision("DENY", "failed_validation", identity.agent_id, record)

    # 4. Low average reputation check (0-100 scale)
    if (
        signals.reputation_count > 0
        and signals.reputation_average_value is not None
        and signals.reputation_average_value < MIN_REPUTATION_SCORE
    ):
        return Decision("DENY", "low_reputation_score", identity.agent_id, record)

    # 5. Semantic classification: KNOWN_BUT_UNTRUSTED
    # Registered and invariant-consistent, but has no reputation or validations yet.
    if record.classification == AgentClassification.KNOWN_BUT_UNTRUSTED:
        return Decision("FLAG", "known_but_untrusted", identity.agent_id, record)

    # 6. Unreachable off-chain registration metadata
    if not identity.registration_file_reachable:
        return Decision("FLAG", "unreachable_registration_file", identity.agent_id, record)

    # 7. Default pass
    return Decision("ALLOW", "ok", identity.agent_id, record)


async def resolve_trust(agent_id: str, client: RegistryClient | None = None) -> Decision:
    """Look up an agent on TRC-8004 and return ALLOW / FLAG / DENY.

    On registry errors (network down, malformed data), fails to FLAG
    rather than ALLOW or DENY.
    """
    client = client or RegistryClient()
    try:
        record = await client.get_agent_record(agent_id)
    except RegistryError as exc:
        return Decision("FLAG", f"registry_unavailable: {exc}", agent_id, None)

    return _decide(record)
