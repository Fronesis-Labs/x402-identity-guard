"""Reference policy: turns a real TRC-8004 Agent record into one decision.

v1 is intentionally a fixed policy, not a config-driven rules engine —
see README > Roadmap for why. If you need different thresholds or
combination logic, fork resolve_trust(); it's short on purpose.

Field names below are confirmed directly from a live trc8004-m2m
install's Agent.model_fields (2026-08-09), not documentation guesses:
exists/active/verified are booleans, feedback_positive/neutral/negative
and total_feedback are counts, total_validations/validations_completed/
validations_rejected are counts. No 0-100 score of any kind exists on
either primitive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry_client import AgentRecord, RegistryClient, RegistryError

Status = Literal["ALLOW", "FLAG", "DENY"]

# Reference-policy constants. Not yet configurable — see README > Roadmap.
# Our own reasonable-looking defaults, not derived from any TRC-8004 spec.
MIN_POSITIVE_RATIO = 0.70   # feedback_positive / total_feedback
MAX_NEGATIVE_FEEDBACK = 10  # absolute count, regardless of ratio
REQUIRE_VALIDATION = True   # if False, "never validated" downgrades FLAG -> ALLOW


@dataclass
class Decision:
    status: Status
    reason: str
    agent_id: str
    record: AgentRecord | None = None


def _decide(record: AgentRecord) -> Decision:
    if not record.exists:
        return Decision("DENY", "no_identity", record.agent_id, record)

    if not record.active:
        return Decision("DENY", "deactivated", record.agent_id, record)

    if record.validations_rejected > 0:
        return Decision("DENY", "failed_validation", record.agent_id, record)

    if record.feedback_negative > MAX_NEGATIVE_FEEDBACK:
        return Decision("DENY", "high_negative_volume", record.agent_id, record)

    if record.total_feedback == 0:
        return Decision("FLAG", "no_feedback_yet", record.agent_id, record)

    ratio = record.feedback_positive / record.total_feedback
    if ratio < MIN_POSITIVE_RATIO:
        return Decision("FLAG", "low_reputation", record.agent_id, record)

    if record.total_validations == 0 and REQUIRE_VALIDATION:
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
