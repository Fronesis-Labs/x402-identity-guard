import pytest

from x402_identity_guard.policy import _decide
from x402_identity_guard.registry_client import (
    AgentClassification,
    AgentIdentity,
    AgentRecord,
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
