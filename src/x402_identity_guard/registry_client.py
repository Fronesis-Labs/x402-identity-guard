"""Secure TRC-8004 registry client used by x402 Identity Guard.

The client deliberately treats registry/RPC failures as verification failures,
not as proof that an agent does not exist. It validates input and response sizes,
normalizes addresses, bounds network calls, isolates cached records from callers,
and derives validation results from individual validation statuses rather than
misinterpreting a registry summary tuple.
"""

from __future__ import annotations

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

from tronpy.keys import is_base58check_address, to_base58check_address

from .cache import TTLCache

try:
    from bankofai.sdk_8004.core.sdk import SDK  # type: ignore
except ImportError:  # pragma: no cover - SDK optional at dev time
    SDK = None  # type: ignore


MAX_UINT256 = (1 << 256) - 1
MAX_CHAIN_ID = (1 << 63) - 1
DEFAULT_MAX_AGENT_ID_LENGTH = 128
DEFAULT_MAX_METADATA_VALUE_BYTES = 4096
DEFAULT_MAX_REGISTRATION_URI_LENGTH = 8192
DEFAULT_MAX_REPUTATION_CLIENTS = 10_000
DEFAULT_MAX_VALIDATIONS = 10_000
DEFAULT_LOOKUP_TIMEOUT_SECONDS = 10.0
DEFAULT_CACHE_TTL_SECONDS = 120.0
DEFAULT_VALIDATION_PASS_SCORE = 100

_AGENT_ID_RE = re.compile(r"^(?P<chain>[0-9]+)(?::(?P<token>[0-9]+))?$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_ZERO_HEX_ADDRESSES = {"0x" + "0" * 40, "41" + "0" * 40}
# Common TRON representation of the all-zero address.
_ZERO_BASE58_ADDRESSES = {"T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"}


class AgentClassification(Enum):
    VERIFIED = "VERIFIED"
    KNOWN_BUT_UNTRUSTED = "KNOWN_BUT_UNTRUSTED"
    INCONSISTENT_IDENTITY = "INCONSISTENT_IDENTITY"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class AgentIdentity:
    agent_id: str
    exists: bool
    owner: Optional[str]
    wallet: Optional[str]
    token_uri: Optional[str]
    metadata_wallet: Optional[str]
    # This is a registry-field consistency check. It is not proof that owner
    # controls wallet and is intentionally not described as owner == wallet.
    is_consistent: bool
    active_self_reported: bool
    registration_file_reachable: bool
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrustSignals:
    reputation_count: int
    reputation_average_value: Optional[float]
    clients: Tuple[str, ...]
    validation_count: int
    # (passing_validations, total_validations), derived from individual
    # validation responses by RegistryClient.
    validation_summary: Optional[Tuple[int, int]]


@dataclass
class AgentRecord:
    """Aggregated agent evaluation data passed to policy engines."""

    identity: AgentIdentity
    trust_signals: TrustSignals
    classification: AgentClassification


class AgentIdError(ValueError):
    """Raised when an agent identifier is malformed or targets another chain."""


class RegistryError(RuntimeError):
    """Safe, non-sensitive verification failure.

    The public string is a stable error code. The original exception is retained
    only as ``__cause__`` for server-side diagnostics and is never sent to clients
    by this module.
    """

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def normalize_agent_id(
    agent_id: str,
    default_chain_id: int,
    *,
    max_length: int = DEFAULT_MAX_AGENT_ID_LENGTH,
) -> Tuple[str, int]:
    """Return ``(canonical_chain_id_token_id, token_id)`` after strict validation.

    The configured registry/network is authoritative. An explicit chain prefix
    that differs from ``default_chain_id`` is rejected rather than silently being
    queried against the wrong registry.
    """

    if not isinstance(agent_id, str):
        raise AgentIdError("invalid_agent_id")
    if not isinstance(default_chain_id, int) or not 0 <= default_chain_id <= MAX_CHAIN_ID:
        raise AgentIdError("invalid_configured_chain_id")
    if not isinstance(max_length, int) or not 1 <= max_length <= 4096:
        raise AgentIdError("invalid_agent_id_length_limit")

    value = agent_id.strip()
    if value != agent_id or not value or len(value) > max_length:
        raise AgentIdError("invalid_agent_id")
    if _CONTROL_CHARS_RE.search(value):
        raise AgentIdError("invalid_agent_id")

    match = _AGENT_ID_RE.fullmatch(value)
    if match is None:
        raise AgentIdError("invalid_agent_id")

    chain_id = int(match.group("chain"))
    token_id = int(match.group("token") or match.group("chain")) if match.group("token") else int(match.group("chain"))
    if match.group("token") is None:
        chain_id = default_chain_id
    if chain_id != default_chain_id:
        raise AgentIdError("wrong_chain_id")
    if chain_id > MAX_CHAIN_ID or token_id > MAX_UINT256:
        raise AgentIdError("agent_id_out_of_range")

    return f"{chain_id}:{token_id}", token_id


# Backwards-compatible private name used by older callers/tests.
_normalize_agent_id = normalize_agent_id


def decode_bytes_value(
    val: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_METADATA_VALUE_BYTES,
) -> str:
    """Decode bounded ERC-8004 metadata bytes into an address or printable text."""

    if not isinstance(val, (bytes, bytearray, memoryview)):
        raise ValueError("metadata_value_not_bytes")
    raw = bytes(val)
    if len(raw) > max_bytes:
        raise ValueError("metadata_value_too_large")
    if not raw:
        return ""

    if len(raw) == 20:
        tron_hex = "41" + raw.hex()
        try:
            return to_base58check_address(tron_hex)
        except Exception:
            return f"0x{raw.hex()}"

    if len(raw) == 21 and raw[0] == 0x41:
        try:
            return to_base58check_address(raw.hex())
        except Exception:
            return f"0x{raw.hex()}"

    if len(raw) == 32 and raw[:12] == b"\x00" * 12:
        tron_hex = "41" + raw[12:].hex()
        try:
            return to_base58check_address(tron_hex)
        except Exception:
            return f"0x{raw[12:].hex()}"

    try:
        decoded_str = raw.decode("utf-8")
        if decoded_str.isprintable():
            return decoded_str
    except UnicodeDecodeError:
        pass

    return f"0x{raw.hex()}"


def _canonicalize_address(value: Any, *, field: str) -> Optional[str]:
    """Normalize common TRON/EVM address representations without trusting them."""

    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = decode_bytes_value(value)
    if not isinstance(value, str):
        value = str(value)

    text = value.strip()
    if not text or len(text) > 128 or _CONTROL_CHARS_RE.search(text):
        raise RegistryError(f"malformed_{field}")

    lower = text.lower()
    if lower in _ZERO_HEX_ADDRESSES or text in _ZERO_BASE58_ADDRESSES:
        return None

    if text.startswith("T"):
        try:
            if not is_base58check_address(text):
                raise ValueError("invalid_base58_address")
            return to_base58check_address(text)
        except Exception as exc:
            raise RegistryError(f"malformed_{field}") from exc

    # Normalize raw 20-byte EVM or 21-byte TRON hex forms to Base58 where possible.
    hex_part: Optional[str] = None
    if lower.startswith("0x") and len(text) == 42:
        hex_part = text[2:]
    elif lower.startswith("41") and len(text) == 42:
        hex_part = text[2:]
    if hex_part is not None and re.fullmatch(r"[0-9a-fA-F]{40}", hex_part):
        if int(hex_part, 16) == 0:
            return None
        try:
            return to_base58check_address("41" + hex_part.lower())
        except Exception as exc:
            raise RegistryError(f"malformed_{field}") from exc

    return text


def _empty_record(canonical_id: str) -> AgentRecord:
    return AgentRecord(
        identity=AgentIdentity(
            agent_id=canonical_id,
            exists=False,
            owner=None,
            wallet=None,
            token_uri=None,
            metadata_wallet=None,
            is_consistent=False,
            active_self_reported=False,
            registration_file_reachable=False,
        ),
        trust_signals=TrustSignals(
            reputation_count=0,
            reputation_average_value=None,
            clients=(),
            validation_count=0,
            validation_summary=(0, 0),
        ),
        classification=AgentClassification.NOT_FOUND,
    )


class RegistryClient:
    def __init__(
        self,
        network: str = "mainnet",
        rpc_url: str = "https://api.trongrid.io",
        fee_limit: int = 120_000_000,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        lookup_timeout_seconds: float = DEFAULT_LOOKUP_TIMEOUT_SECONDS,
        default_chain_id: int = 1,
        allow_insecure_rpc: bool = False,
        allow_testnet: bool = False,
        max_agent_id_length: int = DEFAULT_MAX_AGENT_ID_LENGTH,
        max_metadata_value_bytes: int = DEFAULT_MAX_METADATA_VALUE_BYTES,
        max_registration_uri_length: int = DEFAULT_MAX_REGISTRATION_URI_LENGTH,
        max_reputation_clients: int = DEFAULT_MAX_REPUTATION_CLIENTS,
        max_validations: int = DEFAULT_MAX_VALIDATIONS,
        validation_pass_score: int = DEFAULT_VALIDATION_PASS_SCORE,
        max_concurrent_lookups: int = 16,
        not_found_predicate: Callable[[BaseException], bool] | None = None,
    ):
        if SDK is None:
            raise ImportError(
                "bankofai.sdk_8004 is not installed. Run: "
                'pip install "git+https://github.com/BofAI/8004-sdk.git#subdirectory=python"'
            )
        if not isinstance(network, str) or not network or len(network) > 64:
            raise ValueError("invalid_network")
        if not isinstance(allow_testnet, bool):
            raise ValueError("allow_testnet must be bool")
        if network.lower() in {"shasta", "nile", "testnet", "devnet"} and not allow_testnet:
            raise ValueError("testnet_requires_explicit_allow_testnet")
        if not isinstance(rpc_url, str) or len(rpc_url) > 2048:
            raise ValueError("invalid_rpc_url")
        parsed = urlparse(rpc_url)
        if parsed.scheme not in ({"https", "http"} if allow_insecure_rpc else {"https"}) or not parsed.netloc:
            raise ValueError("rpc_url_must_use_https")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("rpc_url_must_not_contain_credentials_or_fragment")
        if not isinstance(fee_limit, int) or not 0 < fee_limit <= 1_000_000_000:
            raise ValueError("invalid_fee_limit")
        if not isinstance(cache_ttl_seconds, (int, float)) or not math.isfinite(float(cache_ttl_seconds)) or not 0 <= float(cache_ttl_seconds) <= 86_400:
            raise ValueError("invalid_cache_ttl")
        if not isinstance(lookup_timeout_seconds, (int, float)) or not math.isfinite(float(lookup_timeout_seconds)) or not 0.1 <= float(lookup_timeout_seconds) <= 120:
            raise ValueError("invalid_lookup_timeout")
        if not isinstance(default_chain_id, int) or not 0 <= default_chain_id <= MAX_CHAIN_ID:
            raise ValueError("invalid_chain_id")
        if not isinstance(max_agent_id_length, int) or not 1 <= max_agent_id_length <= 4096:
            raise ValueError("invalid_agent_id_length_limit")
        for name, value, upper in (
            ("max_metadata_value_bytes", max_metadata_value_bytes, 1_048_576),
            ("max_registration_uri_length", max_registration_uri_length, 1_048_576),
            ("max_reputation_clients", max_reputation_clients, 1_000_000),
            ("max_validations", max_validations, 1_000_000),
        ):
            if not isinstance(value, int) or not 1 <= value <= upper:
                raise ValueError(f"invalid_{name}")
        if not isinstance(validation_pass_score, int) or not 0 <= validation_pass_score <= 100:
            raise ValueError("invalid_validation_pass_score")
        if not isinstance(max_concurrent_lookups, int) or not 1 <= max_concurrent_lookups <= 256:
            raise ValueError("invalid_max_concurrent_lookups")
        if not callable(not_found_predicate) and not_found_predicate is not None:
            raise ValueError("invalid_not_found_predicate")

        self._network = network
        self._rpc_url = rpc_url
        self._default_chain_id = default_chain_id
        self._max_agent_id_length = max_agent_id_length
        self._max_metadata_value_bytes = max_metadata_value_bytes
        self._max_registration_uri_length = max_registration_uri_length
        self._max_reputation_clients = max_reputation_clients
        self._max_validations = max_validations
        self._validation_pass_score = validation_pass_score
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_lookups,
            thread_name_prefix="x402-registry",
        )
        self._lookup_timeout_seconds = float(lookup_timeout_seconds)
        self._not_found_predicate = not_found_predicate
        self._sdk = SDK(chainId=default_chain_id, rpcUrl=rpc_url, network=network, feeLimit=fee_limit)
        self._cache: TTLCache[AgentRecord] = TTLCache(ttl_seconds=float(cache_ttl_seconds))

    @property
    def default_chain_id(self) -> int:
        return self._default_chain_id

    @property
    def network(self) -> str:
        return self._network

    async def get_agent_record(self, agent_id: str) -> AgentRecord:
        canonical_id, _ = normalize_agent_id(
            agent_id,
            self._default_chain_id,
            max_length=self._max_agent_id_length,
        )

        cached = self._cache.get(canonical_id)
        if cached is not None:
            return copy.deepcopy(cached)

        loop = asyncio.get_running_loop()
        try:
            record = await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._fetch_sync, canonical_id),
                timeout=self._lookup_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RegistryError("registry_timeout") from exc
        except AgentIdError:
            raise
        except RegistryError:
            raise
        except Exception as exc:
            raise RegistryError("registry_lookup_failed") from exc

        # Never return the same mutable object that is stored in the cache.
        self._cache.set(canonical_id, copy.deepcopy(record))
        return copy.deepcopy(record)

    def close(self) -> None:
        """Stop lookup workers during application shutdown."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _call_contract(self, registry: Any, method: str, *args: Any, error_code: str) -> Any:
        try:
            return self._sdk.web3_client.call_contract(registry, method, *args)
        except Exception as exc:
            raise RegistryError(error_code) from exc

    def _fetch_sync(self, canonical_id: str) -> AgentRecord:
        _, token_id = normalize_agent_id(
            canonical_id,
            self._default_chain_id,
            max_length=self._max_agent_id_length,
        )
        identity_registry = self._sdk.identity_registry

        try:
            owner_raw = self._sdk.web3_client.call_contract(identity_registry, "ownerOf", token_id)
        except Exception as exc:
            if self._not_found_predicate is not None:
                try:
                    if self._not_found_predicate(exc):
                        return _empty_record(canonical_id)
                except Exception as predicate_exc:
                    raise RegistryError("not_found_predicate_failed") from predicate_exc
            # A reverted RPC call can mean either a missing token or an outage.
            # Do not convert an ambiguous exception into DENY.
            raise RegistryError("owner_lookup_failed") from exc

        owner = _canonicalize_address(owner_raw, field="owner")
        if owner is None:
            return _empty_record(canonical_id)

        wallet_raw = self._call_contract(
            identity_registry,
            "getAgentWallet",
            token_id,
            error_code="wallet_lookup_failed",
        )
        token_uri_raw = self._call_contract(
            identity_registry,
            "tokenURI",
            token_id,
            error_code="token_uri_lookup_failed",
        )
        wallet = _canonicalize_address(wallet_raw, field="wallet")
        token_uri = None if token_uri_raw is None else str(token_uri_raw)
        if token_uri is not None and len(token_uri) > self._max_registration_uri_length:
            raise RegistryError("token_uri_too_large")

        metadata_keys = (
            "agentWallet",
            "agentName",
            "x402Support",
            "x402support",
            "trustModels",
            "mcp",
            "a2a",
        )
        raw_metadata: dict[str, Any] = {}
        for key in metadata_keys:
            try:
                value = self._sdk.web3_client.call_contract(identity_registry, "getMetadata", token_id, key)
            except Exception as exc:
                if key == "agentWallet":
                    raise RegistryError("agent_wallet_metadata_lookup_failed") from exc
                raw_metadata[key] = ""
                continue

            try:
                if isinstance(value, (bytes, bytearray, memoryview)):
                    raw_metadata[key] = decode_bytes_value(
                        value,
                        max_bytes=self._max_metadata_value_bytes,
                    )
                elif value is None:
                    raw_metadata[key] = ""
                else:
                    text_value = str(value)
                    if len(text_value) > self._max_metadata_value_bytes:
                        raise ValueError("metadata_value_too_large")
                    raw_metadata[key] = text_value
            except ValueError as exc:
                if key == "agentWallet":
                    raise RegistryError("agent_wallet_metadata_invalid") from exc
                raw_metadata[key] = ""

        metadata_wallet = _canonicalize_address(
            raw_metadata.get("agentWallet") or None,
            field="metadata_wallet",
        )
        is_consistent = (
            owner is not None
            and wallet is not None
            and (metadata_wallet is None or metadata_wallet == wallet)
        )

        registration_file_reachable = False
        active_self_reported = False
        try:
            agent = self._sdk.loadAgent(canonical_id)
            registration_file = getattr(agent, "registration_file", None)
            if registration_file is None:
                raise ValueError("registration_file_missing")
            registration_file_reachable = True
            if isinstance(registration_file, Mapping):
                active_self_reported = bool(registration_file.get("active", False))
            else:
                active_self_reported = bool(getattr(registration_file, "active", False))
        except Exception:
            # Reachability is a soft signal. The policy turns it into FLAG unless
            # an earlier hard-deny rule applies.
            registration_file_reachable = False
            active_self_reported = False

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

        reputation_registry = self._sdk.reputation_registry
        clients_raw = self._call_contract(
            reputation_registry,
            "getClients",
            token_id,
            error_code="reputation_clients_lookup_failed",
        )
        if clients_raw is None:
            clients: tuple[str, ...] = ()
        elif isinstance(clients_raw, (str, bytes, bytearray, memoryview)) or not isinstance(clients_raw, Sequence):
            raise RegistryError("malformed_reputation_clients")
        else:
            if len(clients_raw) > self._max_reputation_clients:
                raise RegistryError("reputation_clients_too_many")
            normalized_clients: list[str] = []
            for client in clients_raw:
                normalized = _canonicalize_address(client, field="reputation_client")
                if normalized is not None:
                    normalized_clients.append(normalized)
            clients = tuple(normalized_clients)

        reputation_count = 0
        reputation_average_value: Optional[float] = None
        if clients:
            try:
                summary = self._sdk.getReputationSummary(canonical_id)
            except Exception as exc:
                raise RegistryError("reputation_summary_lookup_failed") from exc
            if not isinstance(summary, Mapping):
                raise RegistryError("malformed_reputation_summary")
            try:
                reputation_count = int(summary.get("count", 0))
                average_raw = summary.get("averageValue")
                reputation_average_value = float(average_raw) if reputation_count > 0 else None
            except (TypeError, ValueError) as exc:
                raise RegistryError("malformed_reputation_summary") from exc
            if reputation_count < 0 or reputation_count > self._max_reputation_clients:
                raise RegistryError("invalid_reputation_count")
            if reputation_count > 0:
                if reputation_average_value is None or not math.isfinite(reputation_average_value):
                    raise RegistryError("invalid_reputation_average")
                # NOTE: ReputationRegistry.getSummary() encodes feedback as an
                # arbitrary-precision (value: int128, valueDecimals: uint8) pair with
                # no protocol-enforced range (verified against the BofAI SDK's
                # value_encoding.py, 2026-08-15). Clients may give feedback on any
                # scale, so this layer only verifies the value is a usable finite
                # number. A caller-specific scale (e.g. 0-100) is a policy concern,
                # not a registry-integrity concern, and belongs in policy.py.

        validation_registry = self._sdk.validation_registry
        validations_raw = self._call_contract(
            validation_registry,
            "getAgentValidations",
            token_id,
            error_code="validation_list_lookup_failed",
        )
        if validations_raw is None:
            validation_hashes: tuple[Any, ...] = ()
        elif isinstance(validations_raw, (str, bytes, bytearray, memoryview)) or not isinstance(validations_raw, Sequence):
            raise RegistryError("malformed_validation_list")
        else:
            if len(validations_raw) > self._max_validations:
                raise RegistryError("validations_too_many")
            validation_hashes = tuple(validations_raw)

        validation_count = len(validation_hashes)
        passing_validations = 0
        for request_hash in validation_hashes:
            status_raw = self._call_contract(
                validation_registry,
                "getValidationStatus",
                request_hash,
                error_code="validation_status_lookup_failed",
            )
            if not isinstance(status_raw, Sequence) or isinstance(status_raw, (str, bytes, bytearray, memoryview)) or len(status_raw) < 3:
                raise RegistryError("malformed_validation_status")
            try:
                response = int(status_raw[2])
            except (TypeError, ValueError) as exc:
                raise RegistryError("malformed_validation_response") from exc
            if not 0 <= response <= 100:
                raise RegistryError("validation_response_out_of_range")
            if response >= self._validation_pass_score:
                passing_validations += 1

        validation_summary = (passing_validations, validation_count)
        trust_signals = TrustSignals(
            reputation_count=reputation_count,
            reputation_average_value=reputation_average_value,
            clients=clients,
            validation_count=validation_count,
            validation_summary=validation_summary,
        )

        if not is_consistent:
            classification = AgentClassification.INCONSISTENT_IDENTITY
        elif reputation_count > 0 or validation_count > 0:
            classification = AgentClassification.VERIFIED
        else:
            classification = AgentClassification.KNOWN_BUT_UNTRUSTED

        return AgentRecord(
            identity=identity,
            trust_signals=trust_signals,
            classification=classification,
        )
