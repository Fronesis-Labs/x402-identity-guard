from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from x402_identity_guard.middleware import IdentityGuardMiddleware
from x402_identity_guard.registry_client import AgentRecord


class _StubClient:
    """Mimics RegistryClient.get_agent_record without touching the network."""

    def __init__(self, record: AgentRecord):
        self._record = record

    async def get_agent_record(self, agent_id: str) -> AgentRecord:
        return self._record


def _make_app(record: AgentRecord, block_on_flag: bool = False):
    async def homepage(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        IdentityGuardMiddleware,
        client=_StubClient(record),
        block_on_flag=block_on_flag,
    )
    return app


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


def test_no_agent_header_passes_through():
    app = _make_app(_record())
    client = TestClient(app)
    resp = client.get("/")  # no X-Agent-Id header at all
    assert resp.status_code == 200


def test_allowed_agent_reaches_route():
    app = _make_app(_record())
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "agent_test"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_denied_agent_gets_403():
    app = _make_app(_record(exists=False))
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "agent_test"})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "no_identity"


def test_flagged_agent_passes_by_default():
    app = _make_app(_record(feedback_positive=2, feedback_negative=8, total_feedback=10), block_on_flag=False)
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "agent_test"})
    assert resp.status_code == 200


def test_flagged_agent_blocked_when_configured():
    app = _make_app(_record(feedback_positive=2, feedback_negative=8, total_feedback=10), block_on_flag=True)
    client = TestClient(app)
    resp = client.get("/", headers={"X-Agent-Id": "agent_test"})
    assert resp.status_code == 423
    assert resp.json()["reason"] == "low_reputation"
