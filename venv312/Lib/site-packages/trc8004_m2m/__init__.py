"""
TRC-8004-M2M Agent Registry SDK

Machine-to-Machine Agent Registry for TRON blockchain.
Supports agent registration, validation, and reputation management.

Quick Start:
    >>> from trc8004_m2m import AgentRegistry
    >>> 
    >>> registry = AgentRegistry(
    ...     private_key="your_hex_private_key",
    ...     network="mainnet",  # or "shasta", "nile"
    ... )
    >>> 
    >>> # Register a new agent
    >>> agent_id = await registry.register_agent(
    ...     name="My Trading Bot",
    ...     description="AI-powered trading agent",
    ...     skills=[{"id": "trading", "name": "Market Trading"}],
    ...     endpoints=[{"type": "rest_api", "url": "https://api.mybot.com"}],
    ... )
    >>> 
    >>> # Search for agents
    >>> agents = await registry.search_agents(
    ...     skills=["trading"],
    ...     min_feedback_positive=5,
    ...     limit=10
    ... )
"""

from .registry import AgentRegistry
from .agent_protocol import AgentProtocolClient
from .models.agent import Agent, Skill, Endpoint, Validation, Feedback
from .exceptions import (
    RegistryError,
    ContractError,
    NetworkError,
    ValidationError,
)

__version__ = "1.2.5"
__author__ = "TRC-8004-M2M Contributors"

__all__ = [
    # Core
    "AgentRegistry",
    "AgentProtocolClient",
    # Models
    "Agent",
    "Skill",
    "Endpoint",
    "Validation",
    "Feedback",
    # Exceptions
    "RegistryError",
    "ContractError",
    "NetworkError",
    "ValidationError",
]
