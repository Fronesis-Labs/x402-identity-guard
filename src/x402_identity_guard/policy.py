"""Reference policy: turns a TRC-8004 AgentRecord into an identity & trust decision.

Updates the evaluation chain to use AgentIdentity invariants, TrustSignals,
and semantic classifications (such as KNOWN_BUT_UNTRUSTED).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .registry_client import (
    AgentClassification,
    AgentRecord,
    RegistryClient,
    RegistryError,
)

Status = Literal["ALLOW", "FLAG", "DENY"]

# Threshold constants for policy decisions
#
# KNOWN ASSUMPTION (documented, not yet enforced): MIN_REPUTATION_SCORE assumes
# feedback in the connected ReputationRegistry is given on a 0-100 scale. The
# protocol itself does NOT enforce this — feedback is stored as an
# arbitrary-precision (value, valueDecimals) pair and a client could just as
# legitimately leave feedback on a 1-5 scale, a -1/0/1 scale, or anything else
# (see registry_client.py and SECURITY.md for the full detail). If any feedback
# source you rely on doesn't use a 0-100 scale, this threshold will produce
# false DENY decisions for agents with genuinely good reputation. Until this is
# resolved (e.g. once real feedback-source conventions are known from a design
# partner), treat MIN_REPUTATION_SCORE as valid only for 0-100-scale sources.
MIN_REPUTATION_SCORE = 50.0  # Average value threshold (0-100 style)
MAX_NEGATIVE_VALIDATIONS = 0 # Any rejected/negative validation blocks execution


@dataclass
class Decision:
    status: Status
    reason: str
    agent_id: str
    record: AgentRecord | None = None


# A policy is any callable that turns a fetched AgentRecord into a Decision.
# Swap this for your own risk model via resolve_trust(..., policy=my_policy).
PolicyFn = Callable[[AgentRecord], Decision]


def default_policy(record: AgentRecord) -> Decision:
    """The reference policy shipped with this package. See README for the full rule order."""
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

    # 4. Low average reputation check
    # ASSUMES a 0-100 feedback scale — see MIN_REPUTATION_SCORE note above.
    # Not protocol-enforced; may false-DENY agents with non-0-100-scale feedback.
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


# Backwards-compatible alias. `_decide` was the original (private-by-convention)
# name; existing tests and any external code importing it directly keep working.
_decide = default_policy


async def resolve_trust(
    agent_id: str,
    client: RegistryClient | None = None,
    policy: PolicyFn | None = None,
) -> Decision:
    """Look up an agent on TRC-8004 and return ALLOW / FLAG / DENY.

    On registry errors (network down, malformed data), fails to FLAG
    rather than ALLOW or DENY -- this happens before any policy runs,
    since there's no AgentRecord to hand to one.

    `policy` swaps out the decision logic while keeping the registry
    lookup, caching, and error handling above unchanged. Defaults to
    `default_policy` (this module's reference policy) if omitted.
    """
    client = client or RegistryClient()
    active_policy = policy or default_policy
    try:
        record = await client.get_agent_record(agent_id)
    except RegistryError as exc:
        return Decision("FLAG", f"registry_unavailable: {exc}", agent_id, None)

    return active_policy(record)
