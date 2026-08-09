"""Reference policy: turns TRC-8004's three raw primitives into one decision.

v1 is intentionally a fixed policy, not a config-driven rules engine —
see README > Roadmap for why. If you need different thresholds or
combination logic, fork resolve_trust(); it's short on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry_client import AgentRecord, RegistryClient, RegistryError

Status = Literal["ALLOW", "FLAG", "DENY"]

# Reference-policy constants. Not yet configurable — see README > Roadmap.
REPUTATION_THRESHOLD = 50.0
REQUIRE_VALIDATION = True  # if False, "unvalidated" downgrades from FLAG to ALLOW


@dataclass
class Decision:
    status: Status
    reason: str
    agent_id: str
    record: AgentRecord | None = None


def _decide(record: AgentRecord) -> Decision:
    if not record.has_identity:
        return Decision("DENY", "no_identity", record.agent_id, record)

    if record.identity_revoked:
        return Decision("DENY", "identity_revoked", record.agent_id, record)

    if record.latest_validation_status == "rejected":
        return Decision("DENY", "failed_validation", record.agent_id, record)

    if record.reputation_score is not None and record.reputation_score < REPUTATION_THRESHOLD:
        return Decision("FLAG", "low_reputation", record.agent_id, record)

    if record.latest_validation_status is None and REQUIRE_VALIDATION:
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
