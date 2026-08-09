"""Reference policy: turns TRC-8004's three raw primitives into one decision.

v1 is intentionally a fixed policy, not a config-driven rules engine —
see README > Roadmap for why. If you need different thresholds or
combination logic, fork resolve_trust(); it's short on purpose.

Rules below are shaped around what's actually on-chain (no numeric
identity/reputation score exists in TRC-8004 — reputation is raw
Positive/Negative sentiment feedback, validation is a request/
complete/reject workflow with no aggregate score). MIN_SENTIMENT_RATIO
and MAX_NEGATIVE_REVIEWS are still our own guesses at reasonable
values, same as the old numeric threshold was — not derived from any
external spec. Revisit both once real agents have real feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry_client import AgentRecord, RegistryClient, RegistryError

Status = Literal["ALLOW", "FLAG", "DENY"]

# Reference-policy constants. Not yet configurable — see README > Roadmap.
MIN_SENTIMENT_RATIO = 0.70  # positive / (positive + negative)
MAX_NEGATIVE_REVIEWS = 10   # absolute count, regardless of ratio
REQUIRE_VALIDATION = True   # if False, "never validated" downgrades FLAG -> ALLOW


@dataclass
class Decision:
    status: Status
    reason: str
    agent_id: str
    record: AgentRecord | None = None


def _decide(record: AgentRecord) -> Decision:
    if not record.has_identity:
        return Decision("DENY", "no_identity", record.agent_id, record)

    if record.validation_last_status == "rejected":
        return Decision("DENY", "failed_validation", record.agent_id, record)

    if record.reputation_negative > MAX_NEGATIVE_REVIEWS:
        return Decision("DENY", "high_negative_volume", record.agent_id, record)

    total_feedback = record.reputation_positive + record.reputation_negative
    if total_feedback > 0:
        ratio = record.reputation_positive / total_feedback
        if ratio < MIN_SENTIMENT_RATIO:
            return Decision("FLAG", "low_reputation", record.agent_id, record)
    else:
        return Decision("FLAG", "no_feedback_yet", record.agent_id, record)

    if record.validation_last_status is None and REQUIRE_VALIDATION:
        return Decision("FLAG", "unvalidated", record.agent_id, record)

    return Decision("ALLOW", "ok", record.agent_id, record)


async def resolve_trust(agent_id: str, client: RegistryClient | None = None) -> Decision:
    """Look up an agent on TRC-8004 and return ALLOW / FLAG / DENY.

    On registry errors (network down, malformed data), fails to FLAG
    rather than ALLOW or DENY — an unreachable registry shouldn't
    silently let anyone through, but it also shouldn't hard-block
    your whole server on an outage you don't control.
    """
    client = client or RegistryClient()
    try:
        record = await client.get_agent_record(agent_id)
    except RegistryError as exc:
        return Decision("FLAG", f"registry_unavailable: {exc}", agent_id, None)

    return _decide(record)
