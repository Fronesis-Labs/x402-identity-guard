"""
TRC-8004-M2M SDK Exceptions

Custom exception hierarchy for clear error handling.
"""

from typing import Optional, Any


class RegistryError(Exception):
    """Base exception for all SDK errors."""
    
    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.code = code or "REGISTRY_ERROR"
        self.details = details
    
    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {super().__str__()} - {self.details}"
        return f"[{self.code}] {super().__str__()}"


class ConfigurationError(RegistryError):
    """Configuration-related errors."""
    
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, "CONFIGURATION_ERROR", details)


class ContractError(RegistryError):
    """Smart contract interaction errors."""
    
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, "CONTRACT_ERROR", details)


class NetworkError(RegistryError):
    """Network and RPC errors."""
    
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, "NETWORK_ERROR", details)


class ValidationError(RegistryError):
    """Data validation errors."""
    
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, "VALIDATION_ERROR", details)


class StorageError(RegistryError):
    """IPFS and storage errors."""
    
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, "STORAGE_ERROR", details)


class AuthenticationError(RegistryError):
    """Authentication and signature errors."""
    
    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message, "AUTHENTICATION_ERROR", details)
