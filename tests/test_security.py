from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.testclient import TestClient
from starlette.routing import Route

from x402_identity_guard.middleware import IdentityGuardMiddleware
from x402_identity_guard.policy import Decision
from x402_identity_guard.registry_client import (
    AgentClassification,
    AgentIdError,
    AgentIdentity,
    AgentRecord,
    RegistryClient,
    RegistryError,
    TrustSignals,
    normalize_agent_id,
)


class FakeWeb3:
    def __init__(self, values=None, failures=None):
        self.values = values or {}
        self.failures = failures or {}

    def call_contract(self, registry, method, *args):
        if method in self.failures:
            failure = self.failures[method]
            raise failure if isinstance(failure, BaseException) else RuntimeError(str(failure))
        value = self.values.get(method)
        if callable(value):
            return value(*args)
        return value


class FakeSdk:
    def __init__(self, web3, *, registration_active=True):
        self.web3_client = web3
        self.identity_registry = "identity"
        self.reputation_registry = "reputation"
        self.validation_registry = "validation"
        self.registration_active = registration_active

    def loadAgent(self, canonical_id):
        return type(
            "LoadedAgent",
            (),
            {"registration_file": type("Registration", (), {"active": self.registration_active})()},
        )()

    def getReputationSummary(self, canonical_id):
        return {"count": 0, "averageValue": None}


def make_client_for_sync(fake_sdk, **overrides):
    client = object.__new__(RegistryClient)
    client._sdk = fake_sdk
    client._network = "shasta"
    client._rpc_url = "https://example.test/rpc"
    client._default_chain_id = 1
    client._max_agent_id_length = 128
    client._max_metadata_value_bytes = 4096
    client._max_registration_uri_length = 8192
    client._max_reputation_clients = 10_000
    client._max_validations = 10_000
    client._validation_pass_score = 100
    client._lookup_timeout_seconds = 1.0
    client._executor = ThreadPoolExecutor(max_workers=2)
    client._not_found_predicate = None
    from x402_identity_guard.cache import TTLCache
    client._cache = TTLCache(ttl_seconds=120)
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


def base_values():
    return {
        "ownerOf": "41" + "11" * 20,
        "getAgentWallet": "41" + "22" * 20,
        "tokenURI": "https://example.test/agent.json",
        "getMetadata": lambda token_id, key: bytes.fromhex("22" * 20) if key == "agentWallet" else b"",
        "getClients": [],
        "getAgentValidations": [],
    }


def make_record(agent_id="1:42"):
    identity = AgentIdentity(
        agent_id=agent_id,
        exists=True,
        owner="Towner",
        wallet="Twallet",
        token_uri="https://example.test/agent.json",
        metadata_wallet="Twallet",
        is_consistent=True,
        active_self_reported=True,
        registration_file_reachable=True,
    )
    signals = TrustSignals(0, None, (), 0, (0, 0))
    return AgentRecord(identity, signals, AgentClassification.KNOWN_BUT_UNTRUSTED)


def test_agent_id_is_strictly_normalized():
    assert normalize_agent_id("42", 1) == ("1:42", 42)
    assert normalize_agent_id("1:42", 1) == ("1:42", 42)
    for value in (" 42", "42 ", "1:2:3", "-1", "1:-2", "", "1:x"):
        with pytest.raises(AgentIdError):
            normalize_agent_id(value, 1)
    with pytest.raises(AgentIdError, match="wrong_chain_id"):
        normalize_agent_id("2:42", 1)


def test_owner_lookup_failure_is_not_misclassified_as_not_found():
    web3 = FakeWeb3(failures={"ownerOf": RuntimeError("rpc unavailable")})
    client = make_client_for_sync(FakeSdk(web3))
    with pytest.raises(RegistryError, match="owner_lookup_failed"):
        client._fetch_sync("1:42")


def test_metadata_wallet_mismatch_is_inconsistent():
    values = base_values()
    values["getMetadata"] = lambda token_id, key: bytes.fromhex("33" * 20) if key == "agentWallet" else b""
    client = make_client_for_sync(FakeSdk(FakeWeb3(values=values)))
    record = client._fetch_sync("1:42")
    assert record.identity.is_consistent is False
    assert record.classification == AgentClassification.INCONSISTENT_IDENTITY


def test_validation_summary_is_derived_from_individual_statuses():
    values = base_values()
    values["getAgentValidations"] = ["hash-1", "hash-2"]
    values["getValidationStatus"] = lambda request_hash: ("validator", 42, 100 if request_hash == "hash-1" else 50)
    client = make_client_for_sync(FakeSdk(FakeWeb3(values=values)))
    record = client._fetch_sync("1:42")
    assert record.trust_signals.validation_count == 2
    assert record.trust_signals.validation_summary == (1, 2)


def test_validation_status_out_of_range_fails_closed_as_registry_error():
    values = base_values()
    values["getAgentValidations"] = ["hash-1"]
    values["getValidationStatus"] = ("validator", 42, 101)
    client = make_client_for_sync(FakeSdk(FakeWeb3(values=values)))
    with pytest.raises(RegistryError, match="validation_response_out_of_range"):
        client._fetch_sync("1:42")


def test_reputation_summary_accepts_non_0_100_scale():
    # ReputationRegistry.getSummary() encodes feedback as an arbitrary-precision
    # (value, valueDecimals) pair with no protocol-enforced 0-100 range (BofAI
    # SDK value_encoding.py). A client giving feedback on e.g. a 1-5 scale is
    # legitimate and must not be treated as a registry integrity failure.
    values = base_values()
    values["getClients"] = ["41" + "33" * 20]
    client = make_client_for_sync(FakeSdk(FakeWeb3(values=values)))
    client._sdk.getReputationSummary = lambda canonical_id: {"count": 3, "averageValue": 4.5}
    record = client._fetch_sync("1:42")
    assert record.trust_signals.reputation_average_value == 4.5
    assert record.trust_signals.reputation_count == 3


def test_cache_returns_isolated_copy():
    values = base_values()
    client = make_client_for_sync(FakeSdk(FakeWeb3(values=values)))
    first = asyncio.run(client.get_agent_record("1:42"))
    first.identity.raw_metadata["local_mutation"] = "must-not-leak"
    second = asyncio.run(client.get_agent_record("1:42"))
    assert "local_mutation" not in second.identity.raw_metadata


def test_lookup_timeout_is_registry_error():
    client = make_client_for_sync(FakeSdk(FakeWeb3(values=base_values())))
    client._lookup_timeout_seconds = 0.05
    client._fetch_sync = lambda canonical_id: (time.sleep(0.2), make_record(canonical_id))[1]
    with pytest.raises(RegistryError, match="registry_timeout"):
        asyncio.run(client.get_agent_record("1:42"))


class FakeTrustClient:
    default_chain_id = 1

    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error

    async def get_agent_record(self, agent_id):
        if self.error:
            raise self.error
        return self.decision.record


def app_for(middleware_kwargs, *, calls):
    async def endpoint(request):
        calls.append(True)
        decision = getattr(request.state, "identity_decision", None)
        return JSONResponse({"called": True, "decision": getattr(decision, "status", None)})

    app = Starlette(routes=[Route("/protected", endpoint, methods=["GET"]), Route("/public", endpoint, methods=["GET"])])
    app.add_middleware(IdentityGuardMiddleware, **middleware_kwargs)
    return app


def test_missing_identity_is_rejected_on_protected_route():
    calls = []
    client = FakeTrustClient(decision=Decision("ALLOW", "ok", "1:42", make_record()))
    with TestClient(app_for({"client": client, "protected_paths": {"/protected"}}, calls=calls)) as http:
        response = http.get("/protected")
    assert response.status_code == 401
    assert response.json()["error"] == "agent_identity_required"
    assert calls == []


def test_duplicate_identity_headers_are_rejected():
    calls = []
    client = FakeTrustClient(decision=Decision("ALLOW", "ok", "1:42", make_record()))
    with TestClient(app_for({"client": client, "protected_paths": {"/protected"}}, calls=calls)) as http:
        response = http.get(
            "/protected",
            headers=[("X-Agent-Id", "1:42"), ("X-Agent-Id", "1:43")],
        )
    assert response.status_code == 400
    assert response.json()["reason"] == "duplicate_agent_id_header"
    assert calls == []


def test_invalid_identity_is_rejected_before_registry_lookup():
    calls = []
    client = FakeTrustClient(decision=Decision("ALLOW", "ok", "1:42", make_record()))
    with TestClient(app_for({"client": client, "protected_paths": {"/protected"}}, calls=calls)) as http:
        response = http.get("/protected", headers={"X-Agent-Id": "2:42"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_agent_identity"
    assert calls == []


def test_deny_blocks_downstream_route():
    calls = []
    denied = Decision("DENY", "inconsistent_identity", "1:42", make_record())
    client = FakeTrustClient(decision=denied)
    with TestClient(app_for({"client": client, "policy": lambda record: denied, "protected_paths": {"/protected"}}, calls=calls)) as http:
        response = http.get("/protected", headers={"X-Agent-Id": "1:42"})
    assert response.status_code == 403
    assert calls == []


def test_flag_can_be_blocked_or_forwarded():
    calls = []
    flagged = Decision("FLAG", "known_but_untrusted", "1:42", make_record())
    client = FakeTrustClient(decision=flagged)
    with TestClient(app_for({"client": client, "policy": lambda record: flagged, "protected_paths": {"/protected"}, "block_on_flag": True}, calls=calls)) as http:
        blocked = http.get("/protected", headers={"X-Agent-Id": "1:42"})
    assert blocked.status_code == 423
    assert calls == []

    calls = []
    with TestClient(app_for({"client": client, "policy": lambda record: flagged, "protected_paths": {"/protected"}, "block_on_flag": False}, calls=calls)) as http:
        forwarded = http.get("/protected", headers={"X-Agent-Id": "1:42"})
    assert forwarded.status_code == 200
    assert forwarded.json()["decision"] == "FLAG"
    assert calls == [True]


def test_binding_is_required_when_configured():
    calls = []
    allowed = Decision("ALLOW", "ok", "1:42", make_record())
    client = FakeTrustClient(decision=allowed)

    with TestClient(app_for({
        "client": client,
        "policy": lambda record: allowed,
        "protected_paths": {"/protected"},
        "require_identity_binding": True,
        "identity_binding": lambda request, agent_id: False,
    }, calls=calls)) as http:
        response = http.get("/protected", headers={"X-Agent-Id": "1:42"})
    assert response.status_code == 401
    assert calls == []

    calls = []
    with TestClient(app_for({
        "client": client,
        "policy": lambda record: allowed,
        "protected_paths": {"/protected"},
        "require_identity_binding": True,
        "identity_binding": lambda request, agent_id: agent_id == "1:42",
    }, calls=calls)) as http:
        response = http.get("/protected", headers={"X-Agent-Id": "1:42"})
    assert response.status_code == 200
    assert calls == [True]


def test_invalid_custom_decision_status_is_fail_closed():
    calls = []
    invalid = Decision("MAYBE", "ok", "1:42", make_record())
    client = FakeTrustClient(decision=invalid)
    with TestClient(app_for({"client": client, "policy": lambda record: invalid, "protected_paths": {"/protected"}}, calls=calls)) as http:
        response = http.get("/protected", headers={"X-Agent-Id": "1:42"})
    assert response.status_code == 503
    assert calls == []


def test_registry_error_is_503_on_protected_route():
    calls = []
    client = FakeTrustClient(error=RegistryError("registry_timeout"))
    with TestClient(app_for({"client": client, "protected_paths": {"/protected"}}, calls=calls)) as http:
        response = http.get("/protected", headers={"X-Agent-Id": "1:42"})
    assert response.status_code == 503
    assert response.json()["reason"] == "registry_unavailable"
    assert calls == []


def test_missing_identity_is_allowed_on_unprotected_route():
    calls = []
    client = FakeTrustClient(decision=Decision("ALLOW", "ok", "1:42", make_record()))
    with TestClient(app_for({"client": client}, calls=calls)) as http:
        response = http.get("/public")
    assert response.status_code == 200
    assert calls == [True]
