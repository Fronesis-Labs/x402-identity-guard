import pytest

from x402_identity_guard.policy import resolve_trust
from x402_identity_guard.registry_client import RegistryError


class _FailingClient:
    async def get_agent_record(self, agent_id: str):
        raise RegistryError("simulated outage")


class _WorkingClient:
    def __init__(self, record):
        self._record = record

    async def get_agent_record(self, agent_id: str):
        return self._record


@pytest.mark.asyncio
async def test_registry_outage_flags_not_allows():
    decision = await resolve_trust("agent_x", client=_FailingClient())
    assert decision.status == "FLAG"
    assert "registry_unavailable" in decision.reason
