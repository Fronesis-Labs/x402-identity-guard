"""Offline tests for the Shasta demo. No TRON RPC and no payment."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from x402_identity_guard.policy import Decision
from x402_identity_guard.registry_client import (
    AgentClassification,
    AgentIdentity,
    AgentRecord,
    TrustSignals,
)

_DEMO_PATH = Path(__file__).resolve().parents[1] / "examples" / "shasta_dcl_demo.py"
_SPEC = importlib.util.spec_from_file_location("shasta_dcl_demo", _DEMO_PATH)
assert _SPEC and _SPEC.loader
demo = importlib.util.module_from_spec(_SPEC)
sys.modules["shasta_dcl_demo"] = demo
_SPEC.loader.exec_module(demo)


def _decision(status: str, reason: str) -> Decision:
    classification = {
        "DENY": AgentClassification.NOT_FOUND,
        "FLAG": AgentClassification.KNOWN_BUT_UNTRUSTED,
        "ALLOW": AgentClassification.VERIFIED,
    }[status]
    record = AgentRecord(
        identity=AgentIdentity(
            agent_id="1:36",
            exists=status != "DENY",
            owner=None,
            wallet=None,
            token_uri=None,
            metadata_wallet=None,
            is_consistent=status != "DENY",
            active_self_reported=False,
            registration_file_reachable=status == "ALLOW",
        ),
        trust_signals=TrustSignals(
            reputation_count=1 if status == "ALLOW" else 0,
            reputation_average_value=80.0 if status == "ALLOW" else None,
            clients=(),
            validation_count=0,
            validation_summary=(0, 0),
        ),
        classification=classification,
    )
    return Decision(status, reason, "1:36", record)


def _recording_dcl(tmp_path: Path):
    loaded = demo.load_dcl_functions()
    calls = {"evaluate": 0, "append": 0}
    real_eval = loaded["evaluate_policy"]
    real_chain = loaded["ChainState"]

    def evaluate_policy(response, policy_yaml):
        calls["evaluate"] += 1
        return real_eval(response, policy_yaml)

    class RecordingChain(real_chain):
        def append(self, *args, **kwargs):
            calls["append"] += 1
            return super().append(*args, **kwargs)

    loaded["evaluate_policy"] = evaluate_policy
    loaded["ChainState"] = RecordingChain
    return loaded, calls


@pytest.fixture(scope="module")
def dcl_loaded():
    return demo.load_dcl_functions()


def test_shasta_client_factory_uses_testnet_opt_in(monkeypatch):
    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(demo, "RegistryClient", _Client)
    demo.make_shasta_client()
    assert captured["network"] == "shasta"
    assert captured["allow_testnet"] is True
    assert captured["rpc_url"].startswith("https://")
    assert captured["lookup_timeout_seconds"] == 30.0


@pytest.mark.asyncio
async def test_deny_stops_before_dcl(tmp_path, dcl_loaded):
    loaded, calls = _recording_dcl(tmp_path)
    decision = _decision("DENY", "no_identity")

    async def resolve(agent_id, client=None):
        return decision

    db_path = tmp_path / "deny.db"
    event = await demo.run_demo(
        "1:36",
        db_path=str(db_path),
        resolve=resolve,
        dcl=loaded,
    )
    assert event is None
    assert calls == {"evaluate": 0, "append": 0}
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_registry_failure_stops_before_dcl(tmp_path):
    loaded, calls = _recording_dcl(tmp_path)
    decision = Decision("FLAG", "registry_unavailable: registry_timeout", "1:36", None)

    async def resolve(agent_id, client=None):
        return decision

    event = await demo.run_demo("1:36", db_path=str(tmp_path / "missing.db"), resolve=resolve, dcl=loaded)
    assert event is None
    assert calls == {"evaluate": 0, "append": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ALLOW", "FLAG"])
async def test_allow_and_flag_emit_frozen_event(tmp_path, status):
    loaded, calls = _recording_dcl(tmp_path)
    decision = _decision(status, "ok" if status == "ALLOW" else "known_but_untrusted")

    async def resolve(agent_id, client=None):
        return decision

    db_path = tmp_path / "chain.db"
    event = await demo.run_demo(
        "1:36",
        db_path=str(db_path),
        resolve=resolve,
        dcl=loaded,
    )
    assert calls == {"evaluate": 1, "append": 1}
    assert event["schema_version"] == "1.0"
    assert event["event_type"] == "dcl.audit.evaluated"
    assert event["agent_id"] == "1:36"
    assert event["identity_source"] == "trc8004_registry_read"
    assert event["identity_confidence"] == "unverified"
    assert "authenticated" not in event["identity_confidence"]
    assert event["verdict"] in {"COMMIT", "NO_COMMIT"}
    assert "payment" not in event

    row = sqlite3.connect(db_path).execute(
        "SELECT tx_hash, verdict, agent_id FROM chain"
    ).fetchone()
    assert event["proof"]["tx_hash"] == row[0]
    assert event["proof"]["tx_hash"].startswith("0x")
    assert event["verdict"] == row[1]
    assert row[2] == "1:36"
    assert event["integration"]["network"] == "shasta"
    assert event["metadata"]["identity_status"] == status


def test_event_out_writes_the_same_frozen_event(tmp_path):
    event = {
        "schema_version": "1.0",
        "event_type": "dcl.audit.evaluated",
        "producer": "shasta-dcl-demo",
        "route": "examples/shasta_dcl_demo.py",
        "agent_id": "1:36",
        "verdict": "COMMIT",
        "integration": {"name": "x402-identity-guard", "network": "shasta"},
    }
    path = tmp_path / "shasta_demo_event.json"
    demo.write_event(path, event)
    assert json.loads(path.read_text(encoding="utf-8")) == event


def test_identity_confidence_constant_does_not_claim_authentication():
    lowered = demo.IDENTITY_CONFIDENCE.lower()
    assert lowered == "unverified"
    for banned in ("authenticated", "verified_caller", "owner_proof", "signer"):
        assert banned not in lowered
