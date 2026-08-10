"""
TRC-8004-M2M Storage Module

IPFS integration for metadata storage.
"""

import logging
from typing import Dict, Any, Optional
import httpx

from ..exceptions import StorageError
from ..utils.retry import retry_async

logger = logging.getLogger("trc8004_m2m.storage")


class IPFSStorage:
    """
    IPFS storage client.
    
    Handles uploading and fetching metadata from IPFS.
    """
    
    DEFAULT_GATEWAYS = [
        "https://ipfs.io/ipfs",
        "https://gateway.pinata.cloud/ipfs",
        "https://cloudflare-ipfs.com/ipfs",
    ]
    
    def __init__(
        self,
        upload_endpoint: Optional[str] = None,
        gateway_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize IPFS storage.
        
        Args:
            upload_endpoint: Custom upload API endpoint
            gateway_url: IPFS gateway URL for fetching
            timeout: Request timeout
        """
        self.upload_endpoint = upload_endpoint
        self.gateway_url = gateway_url or self.DEFAULT_GATEWAYS[0]
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        
        logger.info(f"IPFSStorage initialized: gateway={self.gateway_url}")
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    @retry_async(operation_name="ipfs_upload")
    async def upload(self, data: Dict[str, Any]) -> tuple[str, str]:
        """
        Upload data to IPFS.
        
        Args:
            data: Data to upload
        
        Returns:
            Tuple of (ipfs_uri, ipfs_hash)
        
        Raises:
            StorageError: If upload fails
        """
        if not self.upload_endpoint:
            raise StorageError(
                "No IPFS upload endpoint configured. "
                "Use API client's upload_to_ipfs() method instead."
            )
        
        try:
            response = await self.client.post(
                self.upload_endpoint,
                json=data
            )
            response.raise_for_status()
            result = response.json()
            
            ipfs_hash = result.get("hash") or result.get("cid")
            if not ipfs_hash:
                raise StorageError("No IPFS hash in response")
            
            ipfs_uri = f"ipfs://{ipfs_hash}"
            return ipfs_uri, ipfs_hash
            
        except Exception as e:
            raise StorageError(f"IPFS upload failed: {e}")
    
    @retry_async(operation_name="ipfs_fetch")
    async def fetch(self, uri: str) -> Dict[str, Any]:
        """
        Fetch data from IPFS.
        
        Args:
            uri: IPFS URI (ipfs://...) or CID
        
        Returns:
            Fetched data
        
        Raises:
            StorageError: If fetch fails
        """
        # Extract CID
        if uri.startswith("ipfs://"):
            cid = uri.replace("ipfs://", "")
        else:
            cid = uri
        
        # Try gateways in order
        gateways = [self.gateway_url] + [
            g for g in self.DEFAULT_GATEWAYS if g != self.gateway_url
        ]
        
        last_error = None
        for gateway in gateways:
            try:
                url = f"{gateway.rstrip('/')}/{cid}"
                response = await self.client.get(url)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                last_error = e
                logger.warning(f"Gateway {gateway} failed: {e}")
                continue
        
        raise StorageError(f"All IPFS gateways failed: {last_error}")
    
    def format_uri(self, cid: str) -> str:
        """
        Format CID as IPFS URI.
        
        Args:
            cid: IPFS CID
        
        Returns:
            IPFS URI (ipfs://...)
        """
        return f"ipfs://{cid}"
    
    def extract_cid(self, uri: str) -> str:
        """
        Extract CID from IPFS URI.
        
        Args:
            uri: IPFS URI or CID
        
        Returns:
            CID
        """
        if uri.startswith("ipfs://"):
            return uri.replace("ipfs://", "")
        return uri
