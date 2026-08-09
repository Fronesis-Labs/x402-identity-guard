"""Thin wrapper around the trc8004-m2m SDK.

IMPORTANT — verify before shipping:
The public m2mregistry.io docs (as of this writing) show write-path
examples (search_agents, register_agent, request_validation) but not
the exact read-path method names for "get this agent's current
Identity/Reputation/Validation record". The method names below
(get_identity / get_reputation / get_latest_validation) are our
best-guess interface, NOT confirmed against the live SDK.

Before day-2 integration testing: pip install trc8004-m2m, read its
actual client class, and fix the three TODO-marked calls in
_fetch_raw() to match. Everything else in this file (caching,
dataclass shape, error handling) is stable regardless of the exact
underlying method names.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cache import TTLCache

try:
    from trc8004_m2m import Registry  # type: ignore
except ImportError:  # pragma: no cover - SDK optional at dev time
    Registry = None  # type: ignore


@dataclass
class AgentRecord:
    agent_id: str
    has_identity: bool
    identity_revoked: bool
    reputation_score: float | None  # None = no reputation data yet
    latest_validation_status: str | None  # "completed" | "rejected" | None


class RegistryError(RuntimeError):
    """Raised when the registry can't be reached or returns malformed data."""


class RegistryClient:
    def __init__(self, network: str = "shasta", cache_ttl_seconds: float = 120.0):
        if Registry is None:
            raise ImportError(
                "trc8004-m2m is not installed. Run: pip install trc8004-m2m"
            )
        self._registry = Registry(network=network)
        self._cache: TTLCache[AgentRecord] = TTLCache(ttl_seconds=cache_ttl_seconds)

    async def get_agent_record(self, agent_id: str) -> AgentRecord:
        cached = self._cache.get(agent_id)
        if cached is not None:
            return cached

        record = await self._fetch_raw(agent_id)
        self._cache.set(agent_id, record)
        return record

    async def _fetch_raw(self, agent_id: str) -> AgentRecord:
        try:
            # TODO: confirm actual method name for identity lookup
            identity = await self._registry.get_identity(agent_id)
            # TODO: confirm actual method name for reputation lookup
            reputation = await self._registry.get_reputation(agent_id)
            # TODO: confirm actual method name for latest validation lookup
            validation = await self._registry.get_latest_validation(agent_id)
        except Exception as exc:  # noqa: BLE001 - registry SDK exceptions are unconfirmed
            raise RegistryError(f"registry lookup failed for {agent_id}: {exc}") from exc

        return AgentRecord(
            agent_id=agent_id,
            has_identity=identity is not None,
            identity_revoked=bool(getattr(identity, "revoked", False)),
            reputation_score=getattr(reputation, "score", None),
            latest_validation_status=getattr(validation, "status", None),
        )
