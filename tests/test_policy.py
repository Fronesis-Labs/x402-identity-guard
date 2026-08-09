import pytest

from x402_identity_guard.policy import _decide
from x402_identity_guard.registry_client import AgentRecord


def _record(**overrides):
    base = dict(
        agent_id="agent_test",
        has_identity=True,
        identity_revoked=False,
        reputation_score=80.0,
        latest_validation_status="completed",
    )
    base.update(overrides)
    return AgentRecord(**base)


def test_no_identity_denies():
    decision = _decide(_record(has_identity=False))
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"


def test_revoked_identity_denies():
    decision = _decide(_record(identity_revoked=True))
    assert decision.status == "DENY"
    assert decision.reason == "identity_revoked"


def test_failed_validation_denies():
    decision = _decide(_record(latest_validation_status="rejected"))
    assert decision.status == "DENY"
    assert decision.reason == "failed_validation"


def test_low_reputation_flags():
    decision = _decide(_record(reputation_score=10.0))
    assert decision.status == "FLAG"
    assert decision.reason == "low_reputation"


def test_no_validation_flags():
    decision = _decide(_record(latest_validation_status=None))
    assert decision.status == "FLAG"
    assert decision.reason == "unvalidated"


def test_clean_agent_allows():
    decision = _decide(_record())
    assert decision.status == "ALLOW"
    assert decision.reason == "ok"


def test_denial_takes_priority_over_low_reputation():
    # identity_revoked should DENY even if reputation looks fine
    decision = _decide(_record(identity_revoked=True, reputation_score=99.0))
    assert decision.status == "DENY"
