import pytest

from x402_identity_guard.policy import _decide
from x402_identity_guard.registry_client import AgentRecord


def _record(**overrides):
    base = dict(
        agent_id="agent_test",
        exists=True,
        active=True,
        verified=True,
        feedback_positive=9,
        feedback_neutral=0,
        feedback_negative=1,
        total_feedback=10,
        total_validations=1,
        validations_completed=1,
        validations_rejected=0,
    )
    base.update(overrides)
    return AgentRecord(**base)


def test_no_identity_denies():
    decision = _decide(_record(exists=False))
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"


def test_deactivated_agent_denies():
    decision = _decide(_record(active=False))
    assert decision.status == "DENY"
    assert decision.reason == "deactivated"


def test_rejected_validation_denies():
    decision = _decide(_record(validations_rejected=1))
    assert decision.status == "DENY"
    assert decision.reason == "failed_validation"


def test_high_negative_volume_denies_even_with_good_ratio():
    decision = _decide(_record(feedback_positive=900, feedback_negative=100, total_feedback=1000))
    assert decision.status == "DENY"
    assert decision.reason == "high_negative_volume"


def test_no_feedback_yet_flags():
    decision = _decide(_record(feedback_positive=0, feedback_negative=0, total_feedback=0))
    assert decision.status == "FLAG"
    assert decision.reason == "no_feedback_yet"


def test_low_positive_ratio_flags():
    decision = _decide(_record(feedback_positive=2, feedback_negative=8, total_feedback=10))
    assert decision.status == "FLAG"
    assert decision.reason == "low_reputation"


def test_never_validated_flags():
    decision = _decide(_record(total_validations=0, validations_completed=0))
    assert decision.status == "FLAG"
    assert decision.reason == "unvalidated"


def test_clean_agent_allows():
    decision = _decide(_record())
    assert decision.status == "ALLOW"
    assert decision.reason == "ok"


def test_no_identity_takes_priority_over_everything():
    decision = _decide(_record(exists=False, feedback_positive=1000, feedback_negative=0, total_feedback=1000))
    assert decision.status == "DENY"
    assert decision.reason == "no_identity"
