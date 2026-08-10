"""
TRC-8004-M2M Crypto Utilities

Cryptographic functions for hashing and canonical JSON.
"""

import json
import hashlib
from typing import Any, Dict
from Crypto.Hash import keccak


def canonical_json(data: Dict[str, Any]) -> bytes:
    """
    Serialize dict to canonical JSON bytes.
    
    Ensures consistent serialization:
    - Keys sorted alphabetically
    - No whitespace
    - UTF-8 encoding
    
    Args:
        data: Dictionary to serialize
    
    Returns:
        Canonical JSON bytes
    
    Example:
        >>> canonical_json({"b": 2, "a": 1})
        b'{"a":1,"b":2}'
    """
    return json.dumps(
        data,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False
    ).encode("utf-8")


def canonical_json_str(data: Dict[str, Any]) -> str:
    """
    Serialize dict to canonical JSON string.
    
    Args:
        data: Dictionary to serialize
    
    Returns:
        Canonical JSON string
    """
    return json.dumps(
        data,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False
    )


def keccak256_hex(data: bytes) -> str:
    """
    Compute Keccak-256 hash (Ethereum/TRON standard).
    
    Args:
        data: Bytes to hash
    
    Returns:
        Hex string with 0x prefix
    
    Example:
        >>> keccak256_hex(b"hello")
        '0x1c8aff950685c2ed4bc3174f3472287b56d9517b9c948127319a09a7a36deac8'
    """
    hasher = keccak.new(digest_bits=256)
    hasher.update(data)
    return "0x" + hasher.hexdigest()


def keccak256_bytes(data: bytes) -> bytes:
    """
    Compute Keccak-256 hash as raw bytes.
    
    Args:
        data: Bytes to hash
    
    Returns:
        32-byte hash
    """
    hasher = keccak.new(digest_bits=256)
    hasher.update(data)
    return hasher.digest()


def sha256_hex(data: bytes) -> str:
    """
    Compute SHA-256 hash.
    
    Args:
        data: Bytes to hash
    
    Returns:
        Hex string with 0x prefix
    """
    return "0x" + hashlib.sha256(data).hexdigest()


def compute_metadata_hash(metadata: Dict[str, Any]) -> str:
    """
    Compute canonical hash of agent metadata.
    
    Args:
        metadata: Agent metadata dictionary
    
    Returns:
        Keccak-256 hash (0x...)
    
    Example:
        >>> metadata = {"name": "MyAgent", "version": "1.0.0"}
        >>> compute_metadata_hash(metadata)
        '0x...'
    """
    canonical = canonical_json(metadata)
    return keccak256_hex(canonical)


def normalize_hash(value: str) -> str:
    """
    Normalize hash string (lowercase, no 0x prefix).
    
    Args:
        value: Hash string (with or without 0x)
    
    Returns:
        Lowercase hash without 0x
    
    Example:
        >>> normalize_hash("0xABC123")
        'abc123'
    """
    if not value:
        return ""
    cleaned = value.lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    return cleaned
