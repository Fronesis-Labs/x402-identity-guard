"""
TRC-8004-M2M Data Models

Pydantic models for type-safe agent data structures.
Aligned with on-chain contract interfaces.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class Skill(BaseModel):
    """Agent skill/capability definition."""

    skill_id: str = Field(..., description="Unique skill identifier")
    skill_name: str = Field(..., description="Human-readable skill name")
    description: str = Field(..., description="Skill description")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON schema for inputs")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="JSON schema for outputs")


class Endpoint(BaseModel):
    """Agent API endpoint configuration."""

    endpoint_type: str = Field(..., description="Type: rest_api, websocket, grpc")
    url: str = Field(..., description="Endpoint URL")
    name: Optional[str] = Field(None, description="Endpoint name")
    version: Optional[str] = Field(None, description="API version")


class Agent(BaseModel):
    """Complete agent profile."""

    agent_id: int = Field(..., description="On-chain agent ID (NFT token ID)")
    owner_address: str = Field(..., description="TRON address of owner")
    wallet_address: Optional[str] = Field(None, description="Delegated wallet address")

    # Metadata
    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")
    version: str = Field(..., description="Agent version")
    token_uri: str = Field(..., description="IPFS/HTTP URI for full metadata")

    # Capabilities
    skills: List[Skill] = Field(default_factory=list, description="Agent skills")
    endpoints: List[Endpoint] = Field(default_factory=list, description="API endpoints")
    tags: List[str] = Field(default_factory=list, description="Search tags")

    # Status
    verified: bool = Field(False, description="Verification status")
    verification_tier: str = Field("self", description="Verification level")
    active: bool = Field(True, description="Active status")

    # Stats — validation counts (no numeric score, matches contract)
    total_validations: int = Field(0, description="Total validations received")
    validations_completed: int = Field(0, description="Completed validations")
    validations_rejected: int = Field(0, description="Rejected validations")

    # Stats — feedback sentiment counts (no numeric score, matches contract)
    total_feedback: int = Field(0, description="Total feedback submissions")
    feedback_positive: int = Field(0, description="Positive feedback count")
    feedback_neutral: int = Field(0, description="Neutral feedback count")
    feedback_negative: int = Field(0, description="Negative feedback count")

    # Timestamps
    registered_at: datetime = Field(..., description="Registration timestamp")
    last_updated: Optional[datetime] = Field(None, description="Last update timestamp")


class Validation(BaseModel):
    """
    Validation request/response.

    Matches ValidationRegistry contract:
    - No on-chain numeric score
    - Status: pending, completed, rejected, cancelled
    """

    request_id: str = Field(..., description="Unique request ID (bytes32, 0x...)")
    request_data_hash: Optional[str] = Field(None, description="Request data integrity hash")

    requester_address: str = Field(..., description="Address that submitted the request")
    validator_address: str = Field(..., description="Validator's TRON address")
    agent_id: int = Field(..., description="Agent being validated")

    # Request
    request_uri: Optional[str] = Field(None, description="URI to request data")
    request_timestamp: Optional[datetime] = Field(None, description="Request timestamp")

    # Result (set on complete/reject)
    result_uri: Optional[str] = Field(None, description="URI to result data")
    result_hash: Optional[str] = Field(None, description="Result data hash")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")

    # Status
    status: str = Field("pending", description="pending, completed, rejected, cancelled")


class Feedback(BaseModel):
    """
    Reputation feedback submission.

    Matches ReputationRegistry contract:
    - Sentiment enum: positive, neutral, negative (no numeric score)
    - Feedback text stored on-chain
    """

    agent_id: int = Field(..., description="Agent receiving feedback")
    client_address: str = Field(..., description="Client submitting feedback")
    feedback_index: int = Field(..., description="Feedback index for this agent")

    feedback_text: Optional[str] = Field(None, description="Feedback text")
    sentiment: str = Field(..., description="positive, neutral, or negative")

    is_revoked: bool = Field(False, description="Revocation status")
    submitted_at: datetime = Field(..., description="Submission timestamp")

    # Agent response thread
    responses: List[Dict[str, Any]] = Field(default_factory=list, description="Agent responses")


class AgentCreateParams(BaseModel):
    """Parameters for creating a new agent."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    version: str = Field(default="1.0.0")
    skills: List[Skill] = Field(default_factory=list)
    endpoints: List[Endpoint] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata_uri: Optional[str] = Field(None, description="Pre-uploaded metadata URI")
