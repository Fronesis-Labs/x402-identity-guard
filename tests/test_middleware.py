from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from x402_identity_guard.middleware import IdentityGuardMiddleware
from x402_identity_guard.registry_client import (
    AgentClassification,
    AgentIdentity,
    AgentRecord,
    TrustSignals,
)


class _StubClient:
    """Mimics RegistryClient.get_agent_record without touching the network."""

    def __init__(self, record: AgentRecord):
        self._record = record

    async def get_agent_record(self, agent_id: str) -> AgentRecord:
        return self._record


def _make_app(
    record: AgentRecord,
    block_on_flag: bool = False,
    protected_paths: set[str] | None = None,
):
    async def homepage(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        IdentityGuardMiddleware,
        client=_StubClient(record),
        block_on_flag=block_on_flag,
        protected_paths=protected_paths,
    )
    return app


def _record(classification=AgentClassification.VERIFIED, **signal_overrides):
    identity = AgentIdentity(
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
    signals_base = dict(
        reputation_count=5,
        reputation_average_value=90.0,
        clients=(),
        validation_count=1,
        validation_summary=(1, 1),
    )
    signals_base.update(signal_overrides)
    return AgentRecord(
        identity=identity,
        trust_signals=TrustSignals(**signals_base),
        classification=classification,
    )


def test_no_agent_header_passes_through():
    app = _make_app(_record())
    client = TestClient(app)
    resp = client.get("/")  # no X-Agent-Id header at all
    assert resp.status_code == 200


def test_allowed_agent_reaches_route():
    app = _make_app(_record())
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "1:36"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_denied_agent_gets_403():
    app = _make_app(_record(classification=AgentClassification.NOT_FOUND))
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "1:36"})
    assert resp.status_code == 403


def test_flagged_agent_passes_by_default():
    app = _make_app(
        _record(classification=AgentClassification.KNOWN_BUT_UNTRUSTED, reputation_count=0, reputation_average_value=None),
        block_on_flag=False,
    )
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "1:36"})
    assert resp.status_code == 200


def test_flagged_agent_blocked_when_configured():
    app = _make_app(
        _record(classification=AgentClassification.KNOWN_BUT_UNTRUSTED, reputation_count=0, reputation_average_value=None),
        block_on_flag=True,
        protected_paths={"/"},
    )
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "1:36"})
    assert resp.status_code == 423
    assert resp.json()["reason"] == "known_but_untrusted"
