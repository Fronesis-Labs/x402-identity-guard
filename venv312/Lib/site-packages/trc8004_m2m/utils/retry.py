"""
TRC-8004-M2M Retry Utilities

Configurable retry logic with exponential backoff.
"""

import asyncio
import logging
from typing import TypeVar, Callable, Optional
from functools import wraps
import random

logger = logging.getLogger("trc8004_m2m.retry")

T = TypeVar("T")


class RetryConfig:
    """Retry configuration."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter


DEFAULT_RETRY_CONFIG = RetryConfig()


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """
    Calculate exponential backoff delay.
    
    Args:
        attempt: Current attempt number (1-indexed)
        config: Retry configuration
    
    Returns:
        Delay in seconds
    """
    if attempt <= 1:
        return 0.0
    
    # Exponential backoff
    delay = config.base_delay * (config.exponential_base ** (attempt - 2))
    delay = min(delay, config.max_delay)
    
    # Add jitter
    if config.jitter:
        jitter_range = delay * 0.1
        delay += random.uniform(-jitter_range, jitter_range)
    
    return max(0.0, delay)


def is_retryable_error(error: Exception) -> bool:
    """Check if error should trigger retry."""
    error_str = str(error).lower()
    
    # Network errors
    if any(keyword in error_str for keyword in [
        "timeout",
        "connection",
        "network",
        "unavailable",
        "refused",
    ]):
        return True
    
    # RPC errors
    if any(keyword in error_str for keyword in [
        "rpc",
        "node",
        "gateway",
    ]):
        return True
    
    return False


def retry_async(
    config: Optional[RetryConfig] = None,
    operation_name: Optional[str] = None,
):
    """
    Async retry decorator.
    
    Args:
        config: Retry configuration
        operation_name: Operation name for logging
    
    Example:
        >>> @retry_async(config=RetryConfig(max_attempts=5))
        ... async def fetch_data():
        ...     return await api.get("/data")
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG
    
    def decorator(func: Callable) -> Callable:
        op_name = operation_name or func.__name__
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error: Optional[Exception] = None
            
            for attempt in range(1, config.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not is_retryable_error(e):
                        logger.debug(
                            f"Non-retryable error in {op_name}: {type(e).__name__}"
                        )
                        raise
                    
                    if attempt >= config.max_attempts:
                        logger.warning(
                            f"Retry exhausted for {op_name} after {attempt} attempts: {e}"
                        )
                        raise
                    
                    delay = calculate_delay(attempt + 1, config)
                    logger.info(
                        f"Retrying {op_name} (attempt {attempt}/{config.max_attempts}) "
                        f"after {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
            
            # Should never reach here
            if last_error:
                raise last_error
        
        return wrapper
    
    return decorator
