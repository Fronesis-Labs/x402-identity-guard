"""
TRC-8004-M2M Chain Utilities

Blockchain event parsing and data loading utilities.
"""

import logging
import os
from typing import Optional, Any, Dict, List
import httpx

from ..exceptions import NetworkError, StorageError

logger = logging.getLogger("trc8004_m2m.chain_utils")


async def load_request_data(request_uri: str) -> str:
    """
    Load data from URI.
    
    Supports multiple URI protocols:
    - file://: Local filesystem
    - ipfs://: IPFS via gateway
    - http://, https://: Direct HTTP request
    
    Args:
        request_uri: Data URI
    
    Returns:
        Loaded data content (string)
    
    Raises:
        FileNotFoundError: Local file not found
        NetworkError: HTTP request failed
    
    Example:
        >>> # Load from local file
        >>> data = await load_request_data("file:///path/to/file.json")
        >>>
        >>> # Load from IPFS
        >>> data = await load_request_data("ipfs://QmXxx...")
        >>>
        >>> # Load from HTTP URL
        >>> data = await load_request_data("https://example.com/data.json")
    
    Note:
        - IPFS gateway can be configured via IPFS_GATEWAY_URL env var
        - HTTP request timeout is 30 seconds
        - If URI doesn't match known protocols, returns as-is
    """
    # Local file
    if request_uri.startswith("file://"):
        path = request_uri.replace("file://", "", 1)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")
    
    # IPFS content
    if request_uri.startswith("ipfs://"):
        cid = request_uri.replace("ipfs://", "", 1)
        gateway = os.getenv("IPFS_GATEWAY_URL", "https://ipfs.io/ipfs")
        url = f"{gateway.rstrip('/')}/{cid}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except Exception as e:
                raise NetworkError(f"Failed to fetch from IPFS: {e}")
    
    # HTTP(S) URL
    if request_uri.startswith("http://") or request_uri.startswith("https://"):
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(request_uri)
                response.raise_for_status()
                return response.text
            except Exception as e:
                raise NetworkError(f"Failed to fetch from URL: {e}")
    
    # Unknown protocol - return as-is
    return request_uri


def parse_agent_registered_event(tx_receipt: Dict[str, Any]) -> Optional[int]:
    """
    Parse AgentRegistered event from transaction receipt.
    
    Extracts the agent_id from the AgentRegistered event.
    
    Args:
        tx_receipt: Transaction receipt from blockchain
    
    Returns:
        Agent ID if found, None otherwise
    
    Example:
        >>> receipt = await tron.get_transaction_info(tx_id)
        >>> agent_id = parse_agent_registered_event(receipt)
        >>> print(f"Agent ID: {agent_id}")
    """
    try:
        # TRON transaction receipt structure
        logs = tx_receipt.get("log", [])
        
        for log in logs:
            # Look for AgentRegistered event
            # Event signature: AgentRegistered(uint256 indexed agentId, address indexed owner, string tokenURI)
            topics = log.get("topics", [])
            
            if not topics:
                continue
            
            # First topic is event signature hash
            event_sig = topics[0]
            
            # AgentRegistered event signature (keccak256 hash)
            # This is a simplified check - in production, verify the actual hash
            
            # For TRON, data is typically in log["data"] field
            data = log.get("data", "")
            
            # Try to parse agent_id from topics (if indexed) or data
            if len(topics) > 1:
                # Agent ID is typically the first indexed parameter
                try:
                    # Convert hex to int
                    agent_id_hex = topics[1]
                    if isinstance(agent_id_hex, str):
                        agent_id = int(agent_id_hex, 16)
                        return agent_id
                except (ValueError, IndexError):
                    continue
        
        # If not found in logs, try alternative format
        # Some TRON clients return events differently
        events = tx_receipt.get("events", [])
        for event in events:
            if event.get("name") == "AgentRegistered":
                result = event.get("result", {})
                agent_id = result.get("agentId") or result.get("agent_id")
                if agent_id is not None:
                    return int(agent_id)
        
        logger.warning("AgentRegistered event not found in transaction receipt")
        return None
        
    except Exception as e:
        logger.error(f"Failed to parse AgentRegistered event: {e}")
        return None


async def fetch_trongrid_events(
    rpc_url: str,
    contract_address: str,
    event_name: str,
    from_block: Optional[int] = None,
    to_block: Optional[int] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Fetch contract events from TronGrid API.
    
    Uses TronGrid REST API to fetch events with pagination.
    
    Args:
        rpc_url: TronGrid API base URL (e.g., https://api.trongrid.io)
        contract_address: Contract address
        event_name: Event name
        from_block: Starting block number (inclusive)
        to_block: Ending block number (inclusive)
        limit: Max events per page
    
    Returns:
        List of event dicts
    
    Raises:
        NetworkError: If API request fails
    
    Example:
        >>> events = await fetch_trongrid_events(
        ...     rpc_url="https://api.trongrid.io",
        ...     contract_address="TValidationRegistry...",
        ...     event_name="ValidationRequest",
        ...     from_block=1000000,
        ...     to_block=1001000,
        ... )
    
    Note:
        - Uses pagination to fetch all events (max 200 per page)
        - Block range filtering done client-side
        - Only returns confirmed events
    """
    base = rpc_url.rstrip("/")
    url = f"{base}/v1/contracts/{contract_address}/events"
    
    params: Dict[str, Any] = {
        "event_name": event_name,
        "only_confirmed": "true",
        "limit": limit,
    }
    
    items: List[Dict[str, Any]] = []
    
    # Fetch all events with pagination
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                batch = data.get("data", [])
                items.extend(batch)
                
                # Check for next page
                fingerprint = (data.get("meta") or {}).get("fingerprint")
                if not fingerprint:
                    break
                
                params["fingerprint"] = fingerprint
                
            except Exception as e:
                raise NetworkError(f"Failed to fetch events from TronGrid: {e}")
    
    # Filter by block range
    if from_block is not None or to_block is not None:
        filtered = []
        for item in items:
            block = item.get("block_number")
            if block is None:
                filtered.append(item)
                continue
            
            if from_block is not None and block < from_block:
                continue
            if to_block is not None and block > to_block:
                continue
            
            filtered.append(item)
        
        return filtered
    
    return items


async def get_transaction_info(
    tron_client: Any,
    tx_id: str,
) -> Dict[str, Any]:
    """
    Get transaction info and receipt.
    
    Args:
        tron_client: Tronpy client instance
        tx_id: Transaction ID
    
    Returns:
        Transaction info dict
    
    Example:
        >>> info = await get_transaction_info(tron, tx_id)
        >>> agent_id = parse_agent_registered_event(info)
    """
    try:
        # For tronpy, this is typically synchronous
        # But we wrap it for consistency
        info = tron_client.get_transaction_info(tx_id)
        return info
    except Exception as e:
        logger.error(f"Failed to get transaction info: {e}")
        raise NetworkError(f"Failed to get transaction info: {e}")
