"""
TRC-8004-M2M Agent Registry SDK (v2)

Main entry point for the SDK. Provides unified interface to:
- TRON blockchain contracts (write operations)
- REST API backend (fast read operations)
- IPFS storage (metadata)

v2 Contract alignment (ERC-8004 compatible superset):
- EnhancedIdentityRegistry: register (overloads), setAgentURI, setMetadata,
  setAgentWallet (signed+legacy), unsetAgentWallet, deactivate/reactivate
- ValidationRegistry: validationRequest, completeValidation (with tag+response),
  rejectValidation, cancelRequest
- ReputationRegistry: giveFeedback (with value/tags/URI), revokeFeedback,
  appendResponse (with URI/hash)
- IncidentRegistry: reportIncident, respondToIncident, resolveIncident (NEW)
"""

import logging
from typing import List, Optional, Dict, Any

from .blockchain.tron_client import TronClient
from .api.client import RegistryAPI
from .storage.ipfs import IPFSStorage
from .models.agent import Agent, Validation, Feedback
from .utils.crypto import canonical_json, keccak256_bytes, compute_metadata_hash
from .utils.chain_utils import parse_agent_registered_event
from .exceptions import RegistryError, ConfigurationError

logger = logging.getLogger("trc8004_m2m")


class AgentRegistry:
    """
    Unified interface to TRON Agent Registry (v2).

    Handles both on-chain (contracts) and off-chain (API) operations.

    Usage:
        registry = AgentRegistry(
            private_key="your_key",
            network="shasta",
            api_url="http://localhost:8000",
        )

        # Register an agent (on-chain)
        agent_id = await registry.register_agent(
            name="MyAgent",
            description="AI trading agent",
            skills=[...],
            endpoints=[...],
        )

        # Search agents (fast API query)
        agents = await registry.search_agents(query="trading")

        # Report incident (v2)
        await registry.report_incident(agent_id, uri, hash, "failure")
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        network: str = "mainnet",
        api_url: Optional[str] = None,
        identity_address: Optional[str] = None,
        validation_address: Optional[str] = None,
        reputation_address: Optional[str] = None,
        incident_address: Optional[str] = None,
    ):
        self.chain = TronClient(
            private_key=private_key,
            network=network,
            identity_address=identity_address,
            validation_address=validation_address,
            reputation_address=reputation_address,
            incident_address=incident_address,
        )

        api_base = api_url or self._default_api_url(network)
        self.api = RegistryAPI(api_base)
        self.storage = IPFSStorage()

        logger.info(f"AgentRegistry v2 initialized: network={network}, api={api_base}")

    async def close(self):
        """Close all connections."""
        await self.api.close()
        await self.storage.close()

    # ==========================================================================
    # WRITE OPERATIONS (Blockchain)
    # ==========================================================================

    async def register_agent(
        self,
        name: str,
        description: str,
        skills: Optional[List[dict]] = None,
        endpoints: Optional[List[dict]] = None,
        tags: Optional[List[str]] = None,
        version: str = "1.0.0",
        **kwargs,
    ) -> int:
        """
        Register a new agent on-chain.

        1. Builds metadata JSON
        2. Uploads to IPFS via API
        3. Computes metadata hash (keccak256)
        4. Calls IdentityRegistry.register(uri, metadataHash)
        5. Parses agent_id from transaction events
        """
        metadata = {
            "name": name,
            "description": description,
            "version": version,
            "skills": skills or [],
            "endpoints": endpoints or [],
            "tags": tags or [],
            **kwargs,
        }

        token_uri = await self.api.upload_to_ipfs(metadata)
        metadata_hash = keccak256_bytes(canonical_json(metadata))
        tx_id = await self.chain.register_agent(token_uri, metadata_hash)

        logger.info(f"Agent registration tx: {tx_id}")

        try:
            await self.api.sync_agent(tx_id)
        except Exception:
            pass

        return tx_id

    async def register_agent_simple(self) -> str:
        """Register a blank agent (ERC-8004 no-arg overload)."""
        return await self.chain.register_agent_no_arg()

    async def register_agent_uri(self, agent_uri: str) -> str:
        """Register an agent with URI only (ERC-8004 URI-only overload)."""
        return await self.chain.register_agent_uri(agent_uri)

    async def set_agent_wallet(self, agent_id: int, wallet: str) -> str:
        """Set delegated wallet for an agent (legacy)."""
        return await self.chain.set_agent_wallet(agent_id, wallet)

    async def unset_agent_wallet(self, agent_id: int) -> str:
        """Clear agent wallet (ERC-8004)."""
        return await self.chain.unset_agent_wallet(agent_id)

    async def set_agent_uri(self, agent_id: int, new_uri: str) -> str:
        """Update agent URI post-registration (ERC-8004)."""
        return await self.chain.set_agent_uri(agent_id, new_uri)

    async def set_metadata(self, agent_id: int, key: str, value: bytes) -> str:
        """Set per-key metadata (ERC-8004)."""
        return await self.chain.set_metadata(agent_id, key, value)

    async def deactivate_agent(self, agent_id: int) -> str:
        """Deactivate an agent (TRC-8004 extension)."""
        return await self.chain.deactivate_agent(agent_id)

    async def reactivate_agent(self, agent_id: int) -> str:
        """Reactivate an agent (TRC-8004 extension)."""
        return await self.chain.reactivate_agent(agent_id)

    # --- Validation ---

    async def submit_validation(
        self,
        agent_id: int,
        validator_address: str,
        request_uri: str,
        request_data: Optional[dict] = None,
    ) -> str:
        """Submit a validation request for an agent."""
        if request_data:
            data_hash = keccak256_bytes(canonical_json(request_data))
        else:
            data_hash = b"\x00" * 32

        return await self.chain.validation_request(
            agent_id=agent_id,
            validator=validator_address,
            request_uri=request_uri,
            request_data_hash=data_hash,
        )

    async def complete_validation(
        self,
        request_id: str,
        result_uri: str,
        result_data: Optional[dict] = None,
        tag: str = "",
        response: int = 100,
    ) -> str:
        """Complete a validation request (validators only)."""
        request_id_bytes = bytes.fromhex(request_id.replace("0x", ""))

        if result_data:
            result_hash = keccak256_bytes(canonical_json(result_data))
        else:
            result_hash = b"\x00" * 32

        return await self.chain.complete_validation(
            request_id=request_id_bytes,
            result_uri=result_uri,
            result_hash=result_hash,
            tag=tag,
            response=response,
        )

    async def reject_validation(
        self,
        request_id: str,
        result_uri: str = "",
        reason_data: Optional[dict] = None,
        tag: str = "",
        response: int = 0,
    ) -> str:
        """Reject a validation request (validators only)."""
        request_id_bytes = bytes.fromhex(request_id.replace("0x", ""))

        if reason_data:
            reason_hash = keccak256_bytes(canonical_json(reason_data))
        else:
            reason_hash = b"\x00" * 32

        return await self.chain.reject_validation(
            request_id=request_id_bytes,
            result_uri=result_uri,
            reason_hash=reason_hash,
            tag=tag,
            response=response,
        )

    async def cancel_validation(self, request_id: str) -> str:
        """Cancel a validation request (requesters only)."""
        request_id_bytes = bytes.fromhex(request_id.replace("0x", ""))
        return await self.chain.cancel_validation(request_id_bytes)

    # --- Reputation ---

    async def give_feedback(
        self,
        agent_id: int,
        feedback_text: str,
        sentiment: str,
        value: int = 0,
        value_decimals: int = 0,
        tag1: str = "",
        tag2: str = "",
        endpoint: str = "",
        feedback_uri: str = "",
        feedback_hash: bytes = b"\x00" * 32,
    ) -> str:
        """Submit reputation feedback for an agent (v2: with ERC-8004 fields)."""
        return await self.chain.give_feedback(
            agent_id=agent_id,
            feedback_text=feedback_text,
            sentiment=sentiment,
            value=value,
            value_decimals=value_decimals,
            tag1=tag1,
            tag2=tag2,
            endpoint=endpoint,
            feedback_uri=feedback_uri,
            feedback_hash=feedback_hash,
        )

    async def revoke_feedback(self, agent_id: int, feedback_index: int) -> str:
        """Revoke previously submitted feedback."""
        return await self.chain.revoke_feedback(agent_id, feedback_index)

    async def respond_to_feedback(
        self,
        agent_id: int,
        feedback_index: int,
        response_text: str,
        client_address: str = "",
        response_uri: str = "",
        response_hash: bytes = b"\x00" * 32,
    ) -> str:
        """Respond to feedback as agent owner (v2: with ERC-8004 fields)."""
        return await self.chain.append_response(
            agent_id=agent_id,
            feedback_index=feedback_index,
            response_text=response_text,
            client_address=client_address,
            response_uri=response_uri,
            response_hash=response_hash,
        )

    # --- Incidents (v2 — NEW) ---

    async def report_incident(
        self,
        agent_id: int,
        incident_uri: str,
        incident_hash: bytes,
        category: str,
    ) -> str:
        """Report an incident against an agent."""
        return await self.chain.report_incident(
            agent_id=agent_id,
            incident_uri=incident_uri,
            incident_hash=incident_hash,
            category=category,
        )

    async def respond_to_incident(
        self,
        incident_id: int,
        response_uri: str,
        response_hash: bytes,
    ) -> str:
        """Respond to an incident (agent owner/wallet only)."""
        return await self.chain.respond_to_incident(
            incident_id=incident_id,
            response_uri=response_uri,
            response_hash=response_hash,
        )

    async def resolve_incident(self, incident_id: int, resolution: str) -> str:
        """Resolve an incident (reporter only)."""
        return await self.chain.resolve_incident(incident_id, resolution)

    # ==========================================================================
    # READ OPERATIONS (API - Fast)
    # ==========================================================================

    async def get_agent(self, agent_id: int) -> Agent:
        """Get agent by ID (from API cache)."""
        return await self.api.get_agent(agent_id)

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
        """Search agents with filters (fast API query)."""
        return await self.api.search_agents(
            query=query,
            skills=skills,
            tags=tags,
            min_feedback_positive=min_feedback_positive,
            verified_only=verified_only,
            limit=limit,
            offset=offset,
        )

    async def get_agent_reputation(self, agent_id: int) -> dict:
        """Get detailed reputation stats (sentiment breakdown + value aggregates)."""
        return await self.api.get_reputation(agent_id)

    async def get_agent_validations(self, agent_id: int) -> List[dict]:
        """Get validation history."""
        return await self.api.get_validations(agent_id)

    async def get_agent_incidents(self, agent_id: int) -> List[dict]:
        """Get incident history (v2)."""
        return await self.api.get_incidents(agent_id)

    async def get_stats(self) -> dict:
        """Get global registry statistics."""
        return await self.api.get_stats()

    # ==========================================================================
    # VERIFICATION (Blockchain - Trustless)
    # ==========================================================================

    async def verify_ownership(self, agent_id: int) -> str:
        """Verify agent ownership on-chain. Returns owner address."""
        return await self.chain.get_agent_owner(agent_id)

    async def verify_agent_exists(self, agent_id: int) -> bool:
        """Check if agent exists on-chain."""
        return await self.chain.agent_exists(agent_id)

    async def verify_agent_active(self, agent_id: int) -> bool:
        """Check if agent is active on-chain (v2)."""
        return await self.chain.is_active(agent_id)

    # ==========================================================================
    # Private helpers
    # ==========================================================================

    @staticmethod
    def _default_api_url(network: str) -> str:
        """Get default API URL for network."""
        urls = {
            "mainnet": "https://registry-api.trc8004.io",
            "shasta": "http://localhost:8000",
            "nile": "http://localhost:8000",
        }
        return urls.get(network, "http://localhost:8000")
