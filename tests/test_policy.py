import pytest

from x402_identity_guard.policy import Decision, _decide, default_policy, resolve_trust
from x402_identity_guard.registry_client import (
    AgentClassification,
    AgentIdentity,
    AgentRecord,
    RegistryError,
    TrustSignals,
)


def _identity(**overrides):
    base = dict(
        agent_id="1:36",
        exists=True,
        owner="TDkW667J6RWm5eCwokE4jgTJ6JV2PfYBEz",
        wallet="TDkW667J6RWm5eCwokE4jgTJ6JV2PfYBEz",
        token_uri="https://example.com/agent/36.json",
        metadata_wallet="TDkW667J6RWm5eCwokE4jgTJ6JV2PfYBEz",
        is_consistent=True,
        active_self_reported=True,
        registration_file_reachable=True,
    )
    base.update(overrides)
    return AgentIdentity(**base)


def _signals(**overrides):
    base = dict(
        reputation_count=0,
        reputation_average_value=None,
        clients=(),
        validation_count=0,
        validation_summary=(0, 0),
    )
    base.update(overrides)
    return TrustSignals(**base)


def _record(identity=None, signals=None, classification=AgentClassification.KNOWN_BUT_UNTRUSTED):
    return AgentRecord(
        identity=identity or _identity(),
        trust_signals=signals or _signals(),
        classification=classification,
    )


def test_nonexistent_identity_denies():
    record = _record(
        identity=_identity(exists=False, owner=None, wallet=None, is_consistent=False),
        classification=AgentClassification.NOT_FOUND,
    )
    decision = _decide(record)
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"


def test_inconsistent_identity_denies():
    record = _record(
        identity=_identity(is_consistent=False),
        classification=AgentClassification.INCONSISTENT_IDENTITY,
    )
    decision = _decide(record)
    assert decision.status == "DENY"
    assert decision.reason == "inconsistent_identity"


def test_failed_validation_denies():
    record = _record(
        signals=_signals(validation_count=1, validation_summary=(0, 1)),
        classification=AgentClassification.VERIFIED,
    )
    decision = _decide(record)
    assert decision.status == "DENY"
    assert decision.reason == "failed_validation"


def test_low_reputation_score_denies():
    record = _record(
        signals=_signals(reputation_count=5, reputation_average_value=30.0),
        classification=AgentClassification.VERIFIED,
    )
    decision = _decide(record)
    assert decision.status == "DENY"
    assert decision.reason == "low_reputation_score"


def test_known_but_untrusted_flags():
    record = _record(classification=AgentClassification.KNOWN_BUT_UNTRUSTED)
    decision = _decide(record)
    assert decision.status == "FLAG"
    assert decision.reason == "known_but_untrusted"


def test_unreachable_registration_file_flags():
    record = _record(
        identity=_identity(registration_file_reachable=False),
        signals=_signals(reputation_count=5, reputation_average_value=90.0, validation_summary=(1, 1)),
        classification=AgentClassification.VERIFIED,
    )
    decision = _decide(record)
    assert decision.status == "FLAG"
    assert decision.reason == "unreachable_registration_file"


def test_clean_verified_agent_allows():
    record = _record(
        signals=_signals(reputation_count=5, reputation_average_value=90.0, validation_summary=(1, 1)),
        classification=AgentClassification.VERIFIED,
    )
    decision = _decide(record)
    assert decision.status == "ALLOW"
    assert decision.reason == "ok"


def test_no_identity_takes_priority_over_everything():
    record = _record(
        identity=_identity(exists=False, owner=None, wallet=None, is_consistent=False),
        signals=_signals(reputation_count=100, reputation_average_value=100.0),
        classification=AgentClassification.NOT_FOUND,
    )
    decision = _decide(record)
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"


def test_decide_alias_matches_default_policy():
    """_decide is a backwards-compatible alias for default_policy, not a fork of it."""
    assert _decide is default_policy


class _StubClient:
    """Minimal stand-in for RegistryClient — returns a fixed record, hits no network."""

    def __init__(self, record: AgentRecord | None = None, error: Exception | None = None):
        self._record = record
        self._error = error

    async def get_agent_record(self, agent_id: str) -> AgentRecord:
        if self._error is not None:
            raise self._error
        return self._record


@pytest.mark.asyncio
async def test_resolve_trust_uses_default_policy_when_none_given():
    record = _record(classification=AgentClassification.KNOWN_BUT_UNTRUSTED)
    decision = await resolve_trust("1:36", client=_StubClient(record))
    assert decision.status == "FLAG"
    assert decision.reason == "known_but_untrusted"


@pytest.mark.asyncio
async def test_resolve_trust_uses_custom_policy_when_given():
    """A pluggable policy fully overrides the decision, even for records default_policy would DENY."""
    record = _record(
        identity=_identity(is_consistent=False),  # default_policy would DENY this
        classification=AgentClassification.INCONSISTENT_IDENTITY,
    )

    def always_allow(_record: AgentRecord) -> Decision:
        return Decision("ALLOW", "custom_policy_override", _record.identity.agent_id, _record)

    decision = await resolve_trust("1:36", client=_StubClient(record), policy=always_allow)
    assert decision.status == "ALLOW"
    assert decision.reason == "custom_policy_override"


@pytest.mark.asyncio
async def test_resolve_trust_registry_error_flags_before_policy_runs():
    """Registry errors short-circuit to FLAG without ever calling the policy."""
    policy_was_called = False

    def spy_policy(_record: AgentRecord) -> Decision:
        nonlocal policy_was_called
        policy_was_called = True
        return Decision("ALLOW", "unreachable", "1:36", _record)

    client = _StubClient(error=RegistryError("rpc timeout"))
    decision = await resolve_trust("1:36", client=client, policy=spy_policy)

    assert decision.status == "FLAG"
    assert decision.reason.startswith("registry_unavailable")
    assert policy_was_called is False
