"""
TRC-8004-M2M TRON Blockchain Client (v2)

Handles all smart contract interactions on TRON.
Function signatures match the v2 deployed contracts exactly.

Contract interfaces:
- EnhancedIdentityRegistry: register (3 overloads), registerWithURI, registerWithMetadata,
  exists, agentExists, ownerOf, tokenURI, setAgentWallet, setAgentWalletSigned,
  unsetAgentWallet, setAgentURI, setMetadata, getMetadata, deactivate, reactivate, isActive, totalAgents
- ValidationRegistry: validationRequest (2 overloads), completeValidation (2 overloads),
  rejectValidation (2 overloads), cancelRequest, getRequest, requestExists,
  getValidationStatus, getSummaryForAgent, getSummary (filtered)
- ReputationRegistry: giveFeedback (2 overloads), revokeFeedback, appendResponse (2 overloads),
  getFeedback, getFeedbackCount, getFeedbackResponses, getSummary (2 overloads), getClients, getLastIndex
- IncidentRegistry: reportIncident, respondToIncident, resolveIncident,
  getIncident, getIncidents, getSummary (NEW)
"""

import logging
from typing import Optional, Dict, Any, List

from tronpy import Tron
from tronpy.providers import HTTPProvider

from ..exceptions import ContractError, ConfigurationError, NetworkError
from ..utils.retry import retry_async

logger = logging.getLogger("trc8004_m2m.blockchain")

# Network RPC endpoints
NETWORK_URLS = {
    "mainnet": "https://api.trongrid.io",
    "shasta": "https://api.shasta.trongrid.io",
    "nile": "https://nile.trongrid.io",
}

# Sentiment enum: Neutral(0), Positive(1), Negative(2)
SENTIMENT_TO_INT = {"neutral": 0, "positive": 1, "negative": 2}
INT_TO_SENTIMENT = {0: "neutral", 1: "positive", 2: "negative"}

# Incident resolution enum
RESOLUTION_TO_INT = {"none": 0, "acknowledged": 1, "disputed": 2, "fixed": 3, "not_a_bug": 4, "duplicate": 5}


class TronClient:
    """
    TRON blockchain client for TRC-8004 v2 contract interactions.

    All method signatures match the deployed Solidity contracts exactly.
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        network: str = "mainnet",
        identity_address: Optional[str] = None,
        validation_address: Optional[str] = None,
        reputation_address: Optional[str] = None,
        incident_address: Optional[str] = None,
    ):
        rpc_url = NETWORK_URLS.get(network)
        if not rpc_url:
            raise ConfigurationError(f"Unknown network: {network}")

        self.network = network
        self.private_key = private_key

        try:
            self.tron = Tron(provider=HTTPProvider(rpc_url))
            if private_key:
                self.tron.default_address = self.tron.get_address_from_passphrase(private_key)
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize TRON client: {e}")

        self.identity_address = identity_address
        self.validation_address = validation_address
        self.reputation_address = reputation_address
        self.incident_address = incident_address

        logger.info(f"TronClient v2 initialized: network={network}")

    # ==========================================================================
    # EnhancedIdentityRegistry
    # ==========================================================================

    @retry_async(operation_name="register_agent")
    async def register_agent(self, token_uri: str, metadata_hash: bytes) -> str:
        """Call IdentityRegistry.register(string uri, bytes32 metadataHash)."""
        return await self._send_transaction(
            "identity", "register", [token_uri, metadata_hash],
        )

    @retry_async(operation_name="register_agent_no_arg")
    async def register_agent_no_arg(self) -> str:
        """Call IdentityRegistry.register() — no-arg (ERC-8004)."""
        return await self._send_transaction(
            "identity", "register", [],
        )

    @retry_async(operation_name="register_agent_uri")
    async def register_agent_uri(self, agent_uri: str) -> str:
        """Call IdentityRegistry.registerWithURI(string agentURI) (ERC-8004)."""
        return await self._send_transaction(
            "identity", "registerWithURI", [agent_uri],
        )

    @retry_async(operation_name="register_agent_metadata")
    async def register_agent_metadata(self, agent_uri: str, metadata: List[Dict]) -> str:
        """
        Call IdentityRegistry.registerWithMetadata(string agentURI, MetadataEntry[] metadata).
        metadata: list of {"key": str, "value": bytes}
        """
        entries = [(m["key"], m["value"]) for m in metadata]
        return await self._send_transaction(
            "identity", "registerWithMetadata", [agent_uri, entries],
        )

    @retry_async(operation_name="set_agent_wallet")
    async def set_agent_wallet(self, agent_id: int, wallet: str) -> str:
        """Call IdentityRegistry.setAgentWallet(uint256 agentId, address wallet)."""
        return await self._send_transaction(
            "identity", "setAgentWallet", [agent_id, wallet],
        )

    @retry_async(operation_name="set_agent_wallet_signed")
    async def set_agent_wallet_signed(
        self, agent_id: int, wallet: str, deadline: int, v: int, r: bytes, s: bytes
    ) -> str:
        """Call IdentityRegistry.setAgentWalletSigned(agentId, wallet, deadline, v, r, s) (ERC-8004)."""
        return await self._send_transaction(
            "identity", "setAgentWalletSigned", [agent_id, wallet, deadline, v, r, s],
        )

    @retry_async(operation_name="unset_agent_wallet")
    async def unset_agent_wallet(self, agent_id: int) -> str:
        """Call IdentityRegistry.unsetAgentWallet(uint256 agentId) (ERC-8004)."""
        return await self._send_transaction(
            "identity", "unsetAgentWallet", [agent_id],
        )

    @retry_async(operation_name="set_agent_uri")
    async def set_agent_uri(self, agent_id: int, new_uri: str) -> str:
        """Call IdentityRegistry.setAgentURI(uint256 agentId, string newURI) (ERC-8004)."""
        return await self._send_transaction(
            "identity", "setAgentURI", [agent_id, new_uri],
        )

    @retry_async(operation_name="set_metadata")
    async def set_metadata(self, agent_id: int, key: str, value: bytes) -> str:
        """Call IdentityRegistry.setMetadata(uint256 agentId, string key, bytes value) (ERC-8004)."""
        return await self._send_transaction(
            "identity", "setMetadata", [agent_id, key, value],
        )

    @retry_async(operation_name="get_metadata")
    async def get_metadata(self, agent_id: int, key: str) -> bytes:
        """Call IdentityRegistry.getMetadata(uint256 agentId, string key) (ERC-8004)."""
        return await self._call_contract("identity", "getMetadata", [agent_id, key])

    @retry_async(operation_name="deactivate_agent")
    async def deactivate_agent(self, agent_id: int) -> str:
        """Call IdentityRegistry.deactivate(uint256 agentId)."""
        return await self._send_transaction(
            "identity", "deactivate", [agent_id],
        )

    @retry_async(operation_name="reactivate_agent")
    async def reactivate_agent(self, agent_id: int) -> str:
        """Call IdentityRegistry.reactivate(uint256 agentId)."""
        return await self._send_transaction(
            "identity", "reactivate", [agent_id],
        )

    @retry_async(operation_name="is_active")
    async def is_active(self, agent_id: int) -> bool:
        """Call IdentityRegistry.isActive(uint256 agentId)."""
        return await self._call_contract("identity", "isActive", [agent_id])

    @retry_async(operation_name="agent_exists")
    async def agent_exists(self, agent_id: int) -> bool:
        """Call IdentityRegistry.exists(uint256 tokenId)."""
        return await self._call_contract("identity", "exists", [agent_id])

    @retry_async(operation_name="get_agent_owner")
    async def get_agent_owner(self, agent_id: int) -> str:
        """Call IdentityRegistry.ownerOf(uint256 tokenId)."""
        return await self._call_contract("identity", "ownerOf", [agent_id])

    @retry_async(operation_name="get_token_uri")
    async def get_token_uri(self, agent_id: int) -> str:
        """Call IdentityRegistry.tokenURI(uint256 tokenId)."""
        return await self._call_contract("identity", "tokenURI", [agent_id])

    @retry_async(operation_name="get_agent_wallet")
    async def get_agent_wallet(self, agent_id: int) -> str:
        """Call IdentityRegistry.agentWalletOf(uint256 tokenId)."""
        return await self._call_contract("identity", "agentWalletOf", [agent_id])

    @retry_async(operation_name="total_agents")
    async def total_agents(self) -> int:
        """Call IdentityRegistry.totalAgents()."""
        return await self._call_contract("identity", "totalAgents", [])

    # ==========================================================================
    # ValidationRegistry
    # ==========================================================================

    @retry_async(operation_name="validation_request")
    async def validation_request(
        self, agent_id: int, validator: str, request_uri: str, request_data_hash: bytes,
    ) -> str:
        """Call ValidationRegistry.validationRequest(uint256, address, string, bytes32)."""
        return await self._send_transaction(
            "validation", "validationRequest",
            [agent_id, validator, request_uri, request_data_hash],
        )

    @retry_async(operation_name="complete_validation")
    async def complete_validation(
        self, request_id: bytes, result_uri: str, result_hash: bytes,
        tag: str = "", response: int = 100,
    ) -> str:
        """
        Call ValidationRegistry.completeValidation.
        If tag/response provided, uses the v2 overload with tag+response.
        """
        if tag or response != 100:
            return await self._send_transaction(
                "validation", "completeValidation",
                [request_id, result_uri, result_hash, tag, response],
            )
        return await self._send_transaction(
            "validation", "completeValidation",
            [request_id, result_uri, result_hash],
        )

    @retry_async(operation_name="reject_validation")
    async def reject_validation(
        self, request_id: bytes, result_uri: str, reason_hash: bytes,
        tag: str = "", response: int = 0,
    ) -> str:
        """
        Call ValidationRegistry.rejectValidation.
        If tag/response provided, uses the v2 overload with tag+response.
        """
        if tag or response != 0:
            return await self._send_transaction(
                "validation", "rejectValidation",
                [request_id, result_uri, reason_hash, tag, response],
            )
        return await self._send_transaction(
            "validation", "rejectValidation",
            [request_id, result_uri, reason_hash],
        )

    @retry_async(operation_name="cancel_validation")
    async def cancel_validation(self, request_id: bytes) -> str:
        """Call ValidationRegistry.cancelRequest(bytes32 requestId)."""
        return await self._send_transaction(
            "validation", "cancelRequest", [request_id],
        )

    @retry_async(operation_name="get_validation_request")
    async def get_validation_request(self, request_id: bytes) -> Dict[str, Any]:
        """Call ValidationRegistry.getRequest(bytes32 requestId)."""
        return await self._call_contract("validation", "getRequest", [request_id])

    @retry_async(operation_name="request_exists")
    async def request_exists(self, request_id: bytes) -> bool:
        """Call ValidationRegistry.requestExists(bytes32 requestId) (ERC-8004)."""
        return await self._call_contract("validation", "requestExists", [request_id])

    @retry_async(operation_name="get_validation_status")
    async def get_validation_status(self, request_id: bytes) -> Dict[str, Any]:
        """Call ValidationRegistry.getValidationStatus(bytes32 requestId) (ERC-8004)."""
        result = await self._call_contract("validation", "getValidationStatus", [request_id])
        if isinstance(result, (list, tuple)) and len(result) == 5:
            return {
                "status": int(result[0]),
                "response": int(result[1]),
                "tag": result[2],
                "result_uri": result[3],
                "result_hash": result[4],
            }
        return result

    @retry_async(operation_name="get_agent_requests")
    async def get_agent_validation_ids(self, agent_id: int) -> List[bytes]:
        """Call ValidationRegistry.getAgentRequests(uint256 agentId)."""
        return await self._call_contract("validation", "getAgentRequests", [agent_id])

    @retry_async(operation_name="get_validation_summary")
    async def get_validation_summary(self, agent_id: int) -> Dict[str, int]:
        """Call ValidationRegistry.getSummaryForAgent(uint256 agentId)."""
        result = await self._call_contract("validation", "getSummaryForAgent", [agent_id])
        if isinstance(result, (list, tuple)) and len(result) == 7:
            return {
                "total": int(result[0]),
                "pending": int(result[1]),
                "completed": int(result[2]),
                "rejected": int(result[3]),
                "cancelled": int(result[4]),
                "response_sum": int(result[5]),
                "response_count": int(result[6]),
            }
        return result

    # ==========================================================================
    # ReputationRegistry
    # ==========================================================================

    @retry_async(operation_name="give_feedback")
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
        """
        Call ReputationRegistry.giveFeedback.
        Uses full v2 overload if any ERC-8004 fields are set, otherwise legacy.
        """
        sentiment_int = SENTIMENT_TO_INT.get(sentiment.lower())
        if sentiment_int is None:
            raise ContractError(f"Invalid sentiment: {sentiment}. Must be positive/neutral/negative")

        has_erc8004_fields = (value or value_decimals or tag1 or tag2 or endpoint or feedback_uri or feedback_hash != b"\x00" * 32)

        if has_erc8004_fields:
            return await self._send_transaction(
                "reputation", "giveFeedback",
                [agent_id, feedback_text, sentiment_int, value, value_decimals,
                 tag1, tag2, endpoint, feedback_uri, feedback_hash],
            )
        return await self._send_transaction(
            "reputation", "giveFeedback",
            [agent_id, feedback_text, sentiment_int],
        )

    @retry_async(operation_name="revoke_feedback")
    async def revoke_feedback(self, agent_id: int, feedback_index: int) -> str:
        """Call ReputationRegistry.revokeFeedback(uint256 agentId, uint256 feedbackIndex)."""
        return await self._send_transaction(
            "reputation", "revokeFeedback", [agent_id, feedback_index],
        )

    @retry_async(operation_name="append_response")
    async def append_response(
        self,
        agent_id: int,
        feedback_index: int,
        response_text: str,
        client_address: str = "",
        response_uri: str = "",
        response_hash: bytes = b"\x00" * 32,
    ) -> str:
        """
        Call ReputationRegistry.appendResponse.
        Uses full v2 overload if client_address/URI/hash provided.
        """
        has_erc8004_fields = (client_address or response_uri or response_hash != b"\x00" * 32)

        if has_erc8004_fields:
            return await self._send_transaction(
                "reputation", "appendResponse",
                [agent_id, client_address, feedback_index, response_text, response_uri, response_hash],
            )
        return await self._send_transaction(
            "reputation", "appendResponse",
            [agent_id, feedback_index, response_text],
        )

    @retry_async(operation_name="get_feedback")
    async def get_feedback(self, agent_id: int, feedback_index: int) -> Dict[str, Any]:
        """Call ReputationRegistry.getFeedback(uint256, uint256)."""
        result = await self._call_contract(
            "reputation", "getFeedback", [agent_id, feedback_index]
        )
        if isinstance(result, (list, tuple)) and len(result) == 13:
            return {
                "client": result[0],
                "feedback_text": result[1],
                "sentiment": INT_TO_SENTIMENT.get(int(result[2]), "neutral"),
                "value": int(result[3]),
                "value_decimals": int(result[4]),
                "tag1": result[5],
                "tag2": result[6],
                "endpoint": result[7],
                "feedback_uri": result[8],
                "feedback_hash": result[9],
                "timestamp": int(result[10]),
                "revoked": bool(result[11]),
                "response_count": int(result[12]),
            }
        return result

    @retry_async(operation_name="get_feedback_count")
    async def get_feedback_count(self, agent_id: int) -> int:
        """Call ReputationRegistry.getFeedbackCount(uint256 agentId)."""
        return await self._call_contract("reputation", "getFeedbackCount", [agent_id])

    @retry_async(operation_name="get_feedback_responses")
    async def get_feedback_responses(self, agent_id: int, feedback_index: int) -> Dict[str, list]:
        """Call ReputationRegistry.getFeedbackResponses(uint256, uint256)."""
        result = await self._call_contract(
            "reputation", "getFeedbackResponses", [agent_id, feedback_index]
        )
        if isinstance(result, (list, tuple)) and len(result) == 4:
            return {
                "response_texts": list(result[0]),
                "response_uris": list(result[1]),
                "response_hashes": list(result[2]),
                "response_timestamps": [int(t) for t in result[3]],
            }
        return result

    @retry_async(operation_name="get_feedback_summary")
    async def get_feedback_summary(self, agent_id: int) -> Dict[str, Any]:
        """Call ReputationRegistry.getSummary(uint256 agentId)."""
        result = await self._call_contract("reputation", "getSummary", [agent_id])
        if isinstance(result, (list, tuple)) and len(result) == 8:
            return {
                "total": int(result[0]),
                "active": int(result[1]),
                "revoked": int(result[2]),
                "positive": int(result[3]),
                "neutral": int(result[4]),
                "negative": int(result[5]),
                "value_sum": int(result[6]),
                "value_count": int(result[7]),
            }
        return result

    @retry_async(operation_name="get_clients")
    async def get_clients(self, agent_id: int) -> List[str]:
        """Call ReputationRegistry.getClients(uint256 agentId) (ERC-8004)."""
        return await self._call_contract("reputation", "getClients", [agent_id])

    # ==========================================================================
    # IncidentRegistry (v2 — NEW)
    # ==========================================================================

    @retry_async(operation_name="report_incident")
    async def report_incident(
        self, agent_id: int, incident_uri: str, incident_hash: bytes, category: str,
    ) -> str:
        """Call IncidentRegistry.reportIncident(uint256, string, bytes32, string)."""
        return await self._send_transaction(
            "incident", "reportIncident",
            [agent_id, incident_uri, incident_hash, category],
        )

    @retry_async(operation_name="respond_to_incident")
    async def respond_to_incident(
        self, incident_id: int, response_uri: str, response_hash: bytes,
    ) -> str:
        """Call IncidentRegistry.respondToIncident(uint256, string, bytes32)."""
        return await self._send_transaction(
            "incident", "respondToIncident",
            [incident_id, response_uri, response_hash],
        )

    @retry_async(operation_name="resolve_incident")
    async def resolve_incident(self, incident_id: int, resolution: str) -> str:
        """Call IncidentRegistry.resolveIncident(uint256, Resolution)."""
        resolution_int = RESOLUTION_TO_INT.get(resolution.lower(), 0)
        return await self._send_transaction(
            "incident", "resolveIncident",
            [incident_id, resolution_int],
        )

    @retry_async(operation_name="get_incident")
    async def get_incident(self, incident_id: int) -> Dict[str, Any]:
        """Call IncidentRegistry.getIncident(uint256)."""
        return await self._call_contract("incident", "getIncident", [incident_id])

    @retry_async(operation_name="get_agent_incidents")
    async def get_agent_incidents(self, agent_id: int) -> List[int]:
        """Call IncidentRegistry.getIncidents(uint256 agentId)."""
        return await self._call_contract("incident", "getIncidents", [agent_id])

    @retry_async(operation_name="get_incident_summary")
    async def get_incident_summary(self, agent_id: int) -> Dict[str, int]:
        """Call IncidentRegistry.getSummary(uint256 agentId)."""
        result = await self._call_contract("incident", "getSummary", [agent_id])
        if isinstance(result, (list, tuple)) and len(result) == 4:
            return {
                "total": int(result[0]),
                "open": int(result[1]),
                "responded": int(result[2]),
                "resolved": int(result[3]),
            }
        return result

    # ==========================================================================
    # Internal helpers
    # ==========================================================================

    def _get_contract_address(self, contract_name: str) -> str:
        """Get contract address by name."""
        addresses = {
            "identity": self.identity_address,
            "validation": self.validation_address,
            "reputation": self.reputation_address,
            "incident": self.incident_address,
        }
        addr = addresses.get(contract_name)
        if not addr:
            raise ConfigurationError(f"No address configured for {contract_name} contract")
        return addr

    async def _send_transaction(
        self, contract_name: str, function_name: str, params: list,
    ) -> str:
        """Build, sign, and broadcast a contract call transaction."""
        if not self.private_key:
            raise ConfigurationError("Private key required for write operations")

        address = self._get_contract_address(contract_name)

        try:
            contract = self.tron.get_contract(address)
            func = getattr(contract.functions, function_name)
            txn = func(*params)
            txn = txn.with_owner(self.tron.default_address)
            txn = txn.fee_limit(100_000_000)

            signed = txn.sign(self.private_key)
            result = signed.broadcast()

            tx_id = result.get("txid") or result.get("transaction", {}).get("txID")

            logger.info(f"{contract_name}.{function_name} tx: {tx_id}")
            return tx_id

        except Exception as e:
            raise ContractError(
                f"Transaction failed: {contract_name}.{function_name}: {e}"
            )

    async def _call_contract(
        self, contract_name: str, function_name: str, params: list,
    ):
        """Call a view/pure contract function (no gas)."""
        address = self._get_contract_address(contract_name)

        try:
            contract = self.tron.get_contract(address)
            func = getattr(contract.functions, function_name)
            result = func(*params)
            return result

        except Exception as e:
            raise ContractError(
                f"Call failed: {contract_name}.{function_name}: {e}"
            )
