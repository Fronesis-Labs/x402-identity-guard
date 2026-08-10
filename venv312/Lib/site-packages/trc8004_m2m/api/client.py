"""
TRC-8004-M2M Registry API Client

HTTP client for the centralized registry backend (fast queries).
Aligned with backend API response formats.
"""

import logging
from typing import List, Optional, Dict, Any
import httpx

from ..models.agent import Agent, Validation, Feedback
from ..exceptions import NetworkError
from ..utils.retry import retry_async

logger = logging.getLogger("trc8004_m2m.api")


class RegistryAPI:
    """
    REST API client for registry backend.

    Provides fast queries against cached blockchain data.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

        logger.info(f"RegistryAPI initialized: {base_url}")

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    # ==================== AGENT OPERATIONS ====================

    @retry_async(operation_name="api_get_agent")
    async def get_agent(self, agent_id: int) -> Agent:
        """
        Get agent by ID.

        Args:
            agent_id: Agent ID

        Returns:
            Agent model
        """
        try:
            response = await self.client.get(f"{self.base_url}/agents/{agent_id}")
            response.raise_for_status()
            return Agent(**response.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NetworkError(f"Agent {agent_id} not found")
            raise NetworkError(f"Failed to get agent: {e}")
        except Exception as e:
            raise NetworkError(f"API request failed: {e}")

    @retry_async(operation_name="api_search_agents")
    async def search_agents(
        self,
        query: Optional[str] = None,
        skills: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        min_feedback_positive: Optional[int] = None,
        verified_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Agent]:
        """
        Search agents with filters.

        Returns:
            List of agents
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        if query:
            params["query"] = query
        if skills:
            params["skills"] = skills  # FastAPI handles list params
        if tags:
            params["tags"] = tags
        if min_feedback_positive is not None:
            params["min_feedback_positive"] = min_feedback_positive
        if verified_only:
            params["verified_only"] = "true"

        try:
            response = await self.client.get(
                f"{self.base_url}/agents",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            # API returns: {"total": N, "agents": [...], "offset": N, "limit": N}
            agents_data = data.get("agents", [])
            return [Agent(**item) for item in agents_data]
        except Exception as e:
            raise NetworkError(f"Search failed: {e}")

    @retry_async(operation_name="api_sync_agent")
    async def sync_agent(self, agent_id: int) -> Dict[str, Any]:
        """
        Trigger backend to re-sync agent from blockchain.

        Args:
            agent_id: Agent ID

        Returns:
            Sync status
        """
        try:
            response = await self.client.post(f"{self.base_url}/agents/{agent_id}/sync")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise NetworkError(f"Sync failed: {e}")

    # ==================== REPUTATION OPERATIONS ====================

    @retry_async(operation_name="api_get_reputation")
    async def get_reputation(self, agent_id: int) -> Dict[str, Any]:
        """
        Get detailed reputation stats (sentiment breakdown).

        Args:
            agent_id: Agent ID

        Returns:
            Reputation statistics
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/reputation/{agent_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise NetworkError(f"Failed to get reputation: {e}")

    # ==================== VALIDATION OPERATIONS ====================

    @retry_async(operation_name="api_get_validations")
    async def get_validations(
        self,
        agent_id: int,
        limit: int = 50,
    ) -> List[Validation]:
        """
        Get validation history for agent.

        Args:
            agent_id: Agent ID
            limit: Max results

        Returns:
            List of validations
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/validations/{agent_id}",
                params={"limit": limit}
            )
            response.raise_for_status()
            data = response.json()
            return [Validation(**item) for item in data]
        except Exception as e:
            raise NetworkError(f"Failed to get validations: {e}")

    # ==================== STORAGE OPERATIONS ====================

    @retry_async(operation_name="api_upload_metadata")
    async def upload_to_ipfs(self, data: Dict[str, Any]) -> str:
        """
        Upload metadata to IPFS via API.

        Args:
            data: Metadata dictionary

        Returns:
            IPFS URI (ipfs://...)
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/storage/upload",
                json={"data": data},
            )
            response.raise_for_status()
            result = response.json()
            return result["uri"]
        except Exception as e:
            raise NetworkError(f"IPFS upload failed: {e}")

    # ==================== STATS OPERATIONS ====================

    @retry_async(operation_name="api_get_stats")
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get global registry statistics.

        Returns:
            Statistics dictionary
        """
        try:
            response = await self.client.get(f"{self.base_url}/stats")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise NetworkError(f"Failed to get stats: {e}")
