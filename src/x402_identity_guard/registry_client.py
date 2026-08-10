"""Reads agent identity and trust signals from TRC-8004 via bankofai.sdk_8004.

Canonical TRC-8004 deployment uses Bank of AI (BofAI) smart contracts.
This module turns low-level ERC-8004/TRC-8004 contract responses into structured
cryptographic identity assertions (AgentIdentity) and trust evaluation metrics
(TrustSignals).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from tronpy.keys import to_base58check_address

from .cache import TTLCache

try:
    from bankofai.sdk_8004.core.sdk import SDK  # type: ignore
except ImportError:  # pragma: no cover - SDK optional at dev time
    SDK = None  # type: ignore


class AgentClassification(Enum):
    VERIFIED = "VERIFIED"
    KNOWN_BUT_UNTRUSTED = "KNOWN_BUT_UNTRUSTED"
    INCONSISTENT_IDENTITY = "INCONSISTENT_IDENTITY"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class AgentIdentity:
    agent_id: str  # Canonical "chainId:tokenId"
    exists: bool
    owner: Optional[str]
    wallet: Optional[str]
    token_uri: Optional[str]
    metadata_wallet: Optional[str]
    is_consistent: bool  # Cryptographic invariant check: owner == wallet == metadata_wallet
    active_self_reported: bool  # Self-reported in off-chain file if reachable
    registration_file_reachable: bool
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrustSignals:
    reputation_count: int
    reputation_average_value: Optional[float]  # None if reputation_count == 0
    clients: Tuple[str, ...]
    validation_count: int
    validation_summary: Optional[Tuple[int, int]]  # (positive_validations, total_validations)


@dataclass
class AgentRecord:
    """Aggregated agent evaluation data container passed to policy engines."""
    identity: AgentIdentity
    trust_signals: TrustSignals
    classification: AgentClassification


class RegistryError(RuntimeError):
    """Raised when the registry cannot be reached or returns malformed data."""


def _normalize_agent_id(agent_id: str, default_chain_id: int) -> Tuple[str, int]:
    """Return (canonical_agent_id, token_id_int)."""
    if ":" in agent_id:
        chain_str, token_str = agent_id.split(":", 1)
        chain_id = int(chain_str)
    else:
        chain_id = default_chain_id
        token_str = agent_id
    token_id = int(token_str)
    return f"{chain_id}:{token_id}", token_id


def decode_bytes_value(val: bytes) -> str:
    """Decodes raw bytes returned from ERC-8004 getMetadata into a TRON Base58 address or string."""
    if not val:
        return ""

    # 20-byte raw Ethereum/TRON address payload
    if len(val) == 20:
        tron_hex = "41" + val.hex()
        try:
            return to_base58check_address(tron_hex)
        except Exception:
            return f"0x{val.hex()}"

    # 21-byte TRON raw payload starting with 0x41
    if len(val) == 21 and val[0] == 0x41:
        try:
            return to_base58check_address(val.hex())
        except Exception:
            return f"0x{val.hex()}"

    # 32-byte ABI encoded address padding (first 12 bytes zero)
    if len(val) == 32 and val[:12] == b"\x00" * 12:
        tron_hex = "41" + val[12:].hex()
        try:
            return to_base58check_address(tron_hex)
        except Exception:
            return f"0x{val[12:].hex()}"

    # UTF-8 string attempt
    try:
        decoded_str = val.decode("utf-8")
        if decoded_str.isprintable():
            return decoded_str
    except UnicodeDecodeError:
        pass

    return f"0x{val.hex()}"


class RegistryClient:
    def __init__(
        self,
        network: str = "shasta",
        rpc_url: str = "https://api.shasta.trongrid.io",
        fee_limit: int = 120_000_000,
        cache_ttl_seconds: float = 120.0,
    ):
        if SDK is None:
            raise ImportError(
                "bankofai.sdk_8004 is not installed. Run: "
                'pip install "git+https://github.com/BofAI/8004-sdk.git#subdirectory=python"'
            )
        self._sdk = SDK(chainId=1, rpcUrl=rpc_url, network=network, feeLimit=fee_limit)
        self._default_chain_id = 1
        self._cache: TTLCache[AgentRecord] = TTLCache(ttl_seconds=cache_ttl_seconds)

    async def get_agent_record(self, agent_id: str) -> AgentRecord:
        canonical_id, _ = _normalize_agent_id(agent_id, self._default_chain_id)

        cached = self._cache.get(canonical_id)
        if cached is not None:
            return cached

        record = await asyncio.to_thread(self._fetch_sync, canonical_id)
        self._cache.set(canonical_id, record)
        return record

    def _fetch_sync(self, canonical_id: str) -> AgentRecord:
        _, token_id = _normalize_agent_id(canonical_id, self._default_chain_id)

        # ------------------------------------------------------------------
        # 1. IDENTITY & INVARIANTS
        # ------------------------------------------------------------------
        identity_registry = self._sdk.identity_registry

        try:
            owner = self._sdk.web3_client.call_contract(
                identity_registry, "ownerOf", token_id
            )
        except Exception:
            # Token burned or non-existent
            empty_identity = AgentIdentity(
                agent_id=canonical_id,
                exists=False,
                owner=None,
                wallet=None,
                token_uri=None,
                metadata_wallet=None,
                is_consistent=False,
                active_self_reported=False,
                registration_file_reachable=False,
            )
            empty_signals = TrustSignals(
                reputation_count=0,
                reputation_average_value=None,
                clients=(),
                validation_count=0,
                validation_summary=(0, 0),
            )
            return AgentRecord(
                identity=empty_identity,
                trust_signals=empty_signals,
                classification=AgentClassification.NOT_FOUND,
            )

        try:
            wallet = self._sdk.web3_client.call_contract(
                identity_registry, "getAgentWallet", token_id
            )
            token_uri = self._sdk.web3_client.call_contract(
                identity_registry, "tokenURI", token_id
            )
        except Exception as exc:
            raise RegistryError(
                f"Failed to read core identity fields for {canonical_id}: {exc}"
            ) from exc

        # Read & decode metadata probes
        metadata_keys = [
            "agentWallet",
            "agentName",
            "x402Support",
            "x402support",
            "trustModels",
            "mcp",
            "a2a",
        ]
        raw_metadata = {}
        for key in metadata_keys:
            try:
                val_bytes = self._sdk.web3_client.call_contract(
                    identity_registry, "getMetadata", token_id, key
                )
                if isinstance(val_bytes, bytes):
                    raw_metadata[key] = decode_bytes_value(val_bytes)
                else:
                    raw_metadata[key] = str(val_bytes) if val_bytes else ""
            except Exception:
                raw_metadata[key] = ""

        metadata_wallet = raw_metadata.get("agentWallet") or None

        # Check invariant consistency: owner, wallet, and decoded metadata_wallet
        # (If metadata_wallet is specified, it must match wallet)
        is_consistent = (
            owner is not None
            and wallet is not None
            and (metadata_wallet is None or metadata_wallet == wallet)
        )

        active_self_reported = False
        registration_file_reachable = True
        try:
            agent = self._sdk.loadAgent(canonical_id)
            active_self_reported = bool(agent.registration_file.active)
        except Exception:
            registration_file_reachable = False

        identity = AgentIdentity(
            agent_id=canonical_id,
            exists=True,
            owner=owner,
            wallet=wallet,
            token_uri=token_uri,
            metadata_wallet=metadata_wallet,
            is_consistent=is_consistent,
            active_self_reported=active_self_reported,
            registration_file_reachable=registration_file_reachable,
            raw_metadata=raw_metadata,
        )

        # ------------------------------------------------------------------
        # 2. REPUTATION SIGNALS
        # ------------------------------------------------------------------
        reputation_registry = self._sdk.reputation_registry
        try:
            clients_raw = self._sdk.web3_client.call_contract(
                reputation_registry, "getClients", token_id
            )
            clients = tuple(clients_raw) if clients_raw else ()
        except Exception as exc:
            raise RegistryError(
                f"getClients failed for {canonical_id}: {exc}"
            ) from exc

        reputation_count = 0
        reputation_average_value = None

        if clients:
            try:
                summary = self._sdk.getReputationSummary(canonical_id)
                reputation_count = int(summary.get("count", 0))
                reputation_average_value = (
                    float(summary["averageValue"]) if reputation_count > 0 else None
                )
            except Exception as exc:
                raise RegistryError(
                    f"getReputationSummary failed for {canonical_id}: {exc}"
                ) from exc

        # ------------------------------------------------------------------
        # 3. VALIDATION SIGNALS
        # ------------------------------------------------------------------
        validation_registry = self._sdk.validation_registry
        try:
            validations_raw = self._sdk.web3_client.call_contract(
                validation_registry, "getAgentValidations", token_id
            )
            validation_count = len(validations_raw) if validations_raw else 0

            val_summary_raw = self._sdk.web3_client.call_contract(
                validation_registry, "getSummary", token_id, [], ""
            )
            validation_summary = (
                (int(val_summary_raw[0]), int(val_summary_raw[1]))
                if val_summary_raw
                else (0, 0)
            )
        except Exception as exc:
            raise RegistryError(
                f"Validation Registry query failed for {canonical_id}: {exc}"
            ) from exc

        trust_signals = TrustSignals(
            reputation_count=reputation_count,
            reputation_average_value=reputation_average_value,
            clients=clients,
            validation_count=validation_count,
            validation_summary=validation_summary,
        )

        # ------------------------------------------------------------------
        # 4. SEMANTIC CLASSIFICATION
        # ------------------------------------------------------------------
        if not is_consistent:
            classification = AgentClassification.INCONSISTENT_IDENTITY
        elif reputation_count > 0 or validation_summary[1] > 0:
            classification = AgentClassification.VERIFIED
        else:
            classification = AgentClassification.KNOWN_BUT_UNTRUSTED

        return AgentRecord(
            identity=identity,
            trust_signals=trust_signals,
            classification=classification,
        )
