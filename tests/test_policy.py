import pytest

from x402_identity_guard.policy import _decide
from x402_identity_guard.registry_client import AgentRecord, TRON_ZERO_ADDRESS


def _record(**overrides):
    base = dict(
        agent_id="agent_test",
        has_identity=True,
        owner_address="TSomeRealOwnerAddress111111111111",
        reputation_positive=9,
        reputation_negative=1,
        validation_last_status="completed",
    )
    base.update(overrides)
    return AgentRecord(**base)


def test_no_identity_denies():
    decision = _decide(_record(has_identity=False, owner_address=None))
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"


def test_zero_address_owner_is_no_identity():
    # has_identity is computed by the registry client from owner_address,
    # but _decide only trusts has_identity directly — this documents the
    # expected input shape when the owner is the TRON burn address.
    decision = _decide(_record(has_identity=False, owner_address=TRON_ZERO_ADDRESS))
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"


def test_failed_validation_denies():
    decision = _decide(_record(validation_last_status="rejected"))
    assert decision.status == "DENY"
    assert decision.reason == "failed_validation"


def test_high_negative_volume_denies_even_with_good_ratio():
    # 90/100 is a fine ratio (0.9) but 100 negatives crosses the absolute cap
    decision = _decide(_record(reputation_positive=900, reputation_negative=100))
    assert decision.status == "DENY"
    assert decision.reason == "high_negative_volume"


def test_low_sentiment_ratio_flags():
    decision = _decide(_record(reputation_positive=2, reputation_negative=8))
    assert decision.status == "FLAG"
    assert decision.reason == "low_reputation"


def test_no_feedback_yet_flags():
    decision = _decide(_record(reputation_positive=0, reputation_negative=0))
    assert decision.status == "FLAG"
    assert decision.reason == "no_feedback_yet"


def test_never_validated_flags():
    decision = _decide(_record(validation_last_status=None))
    assert decision.status == "FLAG"
    assert decision.reason == "unvalidated"


def test_clean_agent_allows():
    decision = _decide(_record())
    assert decision.status == "ALLOW"
    assert decision.reason == "ok"


def test_no_identity_takes_priority_over_reputation():
    decision = _decide(_record(has_identity=False, reputation_positive=100, reputation_negative=0))
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"
