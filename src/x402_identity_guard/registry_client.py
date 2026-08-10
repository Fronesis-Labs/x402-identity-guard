"""Reads agent state from TRC-8004 via the trc8004-m2m SDK.

Confirmed directly against a live install (trc8004-m2m real package
introspection: dir(trc8004_m2m), AgentRegistry method list, and
Agent/Feedback/Validation.model_fields), not docs guesses — the
docs site (m2mregistry.io) turned out to be internally inconsistent
across pages (different pages named the client TronClient vs
AgentRegistry vs implied a separate RegistryAPI class); none of
those matched the real top-level export. AgentRegistry is the real
class, confirmed 2026-08-09 against a live Shasta install.

One thing not yet confirmed: whether verify_agent_exists()/get_agent()
take agent_id as a keyword arg exactly like this. Every other
documented call across m2mregistry.io consistently used agent_id=,
so this follows that pattern, but hasn't been exercised against a
real registered agent yet.

api_url defaults to the real base URL confirmed at
m2mregistry.io/docs/api ("Base URL: https://m2mregistry.io/api") —
AgentRegistry's own default (http://localhost:8000) is wrong for any
real use and will fail every API-backed call (get_agent,
verify_agent_exists, search_agents) with a connection error.

On registry API outages: the SDK itself already retries internally
(observed "Retry exhausted for api_search_agents after 3 attempts" in
testing) before raising. We deliberately don't add a second retry
layer on top — stacking our own backoff on an already-retried call
would multiply wait time for no real benefit. RegistryError propagates
up to policy.py's resolve_trust(), which fails to FLAG rather than
ALLOW or DENY — see that module's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cache import TTLCache

try:
    from trc8004_m2m import AgentRegistry  # type: ignore
except ImportError:  # pragma: no cover - SDK optional at dev time
    AgentRegistry = None  # type: ignore


@dataclass
class AgentRecord:
    agent_id: str
    exists: bool
    active: bool
    verified: bool
    feedback_positive: int
    feedback_neutral: int
    feedback_negative: int
    total_feedback: int
    total_validations: int
    validations_completed: int
    validations_rejected: int


class RegistryError(RuntimeError):
    """Raised when the registry can't be reached or returns malformed data."""


class RegistryClient:
    def __init__(
        self,
        network: str = "shasta",
        api_url: str = "https://m2mregistry.io/api",
        cache_ttl_seconds: float = 120.0,
    ):
        if AgentRegistry is None:
            raise ImportError(
                "trc8004-m2m is not installed. Run: pip install trc8004-m2m"
            )
        self._registry = AgentRegistry(network=network, api_url=api_url)
        self._cache: TTLCache[AgentRecord] = TTLCache(ttl_seconds=cache_ttl_seconds)

    async def get_agent_record(self, agent_id: str) -> AgentRecord:
        cached = self._cache.get(agent_id)
        if cached is not None:
            return cached

        record = await self._fetch(agent_id)
        self._cache.set(agent_id, record)
        return record

    async def _fetch(self, agent_id: str) -> AgentRecord:
        try:
            exists = await self._registry.verify_agent_exists(agent_id=agent_id)
        except Exception as exc:  # noqa: BLE001 - SDK exception types not yet exercised live
            raise RegistryError(f"existence check failed for {agent_id}: {exc}") from exc

        if not exists:
            return AgentRecord(
                agent_id=agent_id,
                exists=False,
                active=False,
                verified=False,
                feedback_positive=0,
                feedback_neutral=0,
                feedback_negative=0,
                total_feedback=0,
                total_validations=0,
                validations_completed=0,
                validations_rejected=0,
            )

        try:
            agent = await self._registry.get_agent(agent_id=agent_id)
        except Exception as exc:  # noqa: BLE001
            raise RegistryError(f"get_agent failed for {agent_id}: {exc}") from exc

        return AgentRecord(
            agent_id=agent_id,
            exists=True,
            active=agent.active,
            verified=agent.verified,
            feedback_positive=agent.feedback_positive,
            feedback_neutral=agent.feedback_neutral,
            feedback_negative=agent.feedback_negative,
            total_feedback=agent.total_feedback,
            total_validations=agent.total_validations,
            validations_completed=agent.validations_completed,
            validations_rejected=agent.validations_rejected,
        )
