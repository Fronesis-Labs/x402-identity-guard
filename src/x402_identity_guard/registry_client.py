"""Reads agent state from TRC-8004 via the trc8004-m2m SDK.

Confirmed against the real SDK docs (m2mregistry.io/docs/sdk), not
guessed — but the exact JSON/attribute shape RegistryAPI.get_agent(),
get_reputation(), and get_validation_stats() return is still not
fully documented, so _normalize_* below stays defensive (getattr/dict
fallbacks) until we've seen a real response for a registered agent.

Two-tier read, per the registry's own documented architecture:
  1. RegistryAPI (indexed Postgres) — fast path, used by default.
  2. AgentRegistry (on-chain, trustless) — fallback, only hit when the
     fast path returns nothing for an agent_id. This guards against
     indexer lag: a just-registered agent existing on-chain but not
     yet in the index should not be treated the same as "never
     registered".
"""

from __future__ import annotations

from dataclasses import dataclass

from .cache import TTLCache

try:
    from trc8004_m2m import AgentRegistry, RegistryAPI  # type: ignore
except ImportError:  # pragma: no cover - SDK optional at dev time
    AgentRegistry = None  # type: ignore
    RegistryAPI = None  # type: ignore

# TRON's zero/burn address (base58check of all-zero bytes). An agent
# NFT owned by this address, or a get_agent() call that can't resolve
# an owner at all, is treated as "no identity".
TRON_ZERO_ADDRESS = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"


@dataclass
class AgentRecord:
    agent_id: str
    has_identity: bool
    owner_address: str | None
    reputation_positive: int
    reputation_negative: int
    # Last terminal validation event for this agent, if any:
    # "completed" | "rejected" | None (no validation on record yet)
    validation_last_status: str | None


class RegistryError(RuntimeError):
    """Raised when the registry can't be reached or returns malformed data."""


class RegistryClient:
    def __init__(
        self,
        network: str = "shasta",
        api_base_url: str = "https://m2mregistry.io/api",
        cache_ttl_seconds: float = 120.0,
    ):
        if AgentRegistry is None or RegistryAPI is None:
            raise ImportError(
                "trc8004-m2m is not installed. Run: pip install trc8004-m2m"
            )
        self._api = RegistryAPI(base_url=api_base_url)
        self._chain = AgentRegistry(network=network)  # read-only, no private_key
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
            raw_agent = await self._api.get_agent(agent_id=agent_id)
        except Exception as exc:  # noqa: BLE001 - SDK exception types unconfirmed
            raise RegistryError(f"registry API lookup failed for {agent_id}: {exc}") from exc

        # Fast-path miss (indexer lag, or agent genuinely doesn't exist) —
        # fall back to the on-chain read before deciding "no identity".
        if raw_agent is None:
            try:
                raw_agent = await self._chain.get_agent(agent_id=agent_id)
            except Exception as exc:  # noqa: BLE001
                raise RegistryError(
                    f"on-chain fallback failed for {agent_id}: {exc}"
                ) from exc

        owner_address = self._extract_owner(raw_agent)
        has_identity = raw_agent is not None and owner_address not in (None, TRON_ZERO_ADDRESS)

        try:
            raw_reputation = await self._api.get_reputation(agent_id=agent_id)
        except Exception as exc:  # noqa: BLE001
            raise RegistryError(f"reputation lookup failed for {agent_id}: {exc}") from exc

        try:
            raw_validation = await self._api.get_validation_stats(agent_id=agent_id)
        except Exception as exc:  # noqa: BLE001
            raise RegistryError(f"validation stats lookup failed for {agent_id}: {exc}") from exc

        pos, neg = self._normalize_reputation(raw_reputation)
        last_status = self._normalize_validation(raw_validation)

        return AgentRecord(
            agent_id=agent_id,
            has_identity=has_identity,
            owner_address=owner_address,
            reputation_positive=pos,
            reputation_negative=neg,
            validation_last_status=last_status,
        )

    @staticmethod
    def _extract_owner(raw_agent) -> str | None:
        if raw_agent is None:
            return None
        if isinstance(raw_agent, dict):
            return raw_agent.get("owner_address") or raw_agent.get("owner")
        return getattr(raw_agent, "owner_address", None)

    @staticmethod
    def _normalize_reputation(raw_reputation) -> tuple[int, int]:
        """Handle either an aggregate dict {'positive': n, 'negative': n}
        or a raw list of per-feedback entries [{'sentiment': 'Positive'|'Negative'|'Neutral'}, ...].
        Shape not confirmed against a live response yet — this covers both
        documented possibilities; adjust once we've seen the real payload.
        """
        if raw_reputation is None:
            return 0, 0

        if isinstance(raw_reputation, dict) and ("positive" in raw_reputation or "negative" in raw_reputation):
            return int(raw_reputation.get("positive", 0)), int(raw_reputation.get("negative", 0))

        if isinstance(raw_reputation, (list, tuple)):
            pos = sum(1 for entry in raw_reputation if RegistryClient._entry_sentiment(entry) == "positive")
            neg = sum(1 for entry in raw_reputation if RegistryClient._entry_sentiment(entry) == "negative")
            return pos, neg

        return 0, 0

    @staticmethod
    def _entry_sentiment(entry) -> str | None:
        raw = entry.get("sentiment") if isinstance(entry, dict) else getattr(entry, "sentiment", None)
        if raw is None:
            return None
        return str(raw).lower()

    @staticmethod
    def _normalize_validation(raw_validation) -> str | None:
        """Extract the most recent terminal status (completed/rejected) from
        whatever get_validation_stats() returns. Shape not confirmed yet —
        handles a 'last_action'-style dict and a raw history list.
        """
        if raw_validation is None:
            return None

        if isinstance(raw_validation, dict):
            last = raw_validation.get("last_action") or raw_validation.get("status")
            return str(last).lower() if last else None

        if isinstance(raw_validation, (list, tuple)) and raw_validation:
            last_entry = raw_validation[-1]
            status = last_entry.get("status") if isinstance(last_entry, dict) else getattr(last_entry, "status", None)
            return str(status).lower() if status else None

        return None
