"""
TRC-8004-M2M Agent Protocol Client

HTTP client for Agent Protocol standard (agentprotocol.ai).
Enables agent-to-agent (A2A) communication.
"""

import json
import logging
from typing import Dict, Any, Optional
import httpx

from .exceptions import NetworkError
from .utils.retry import retry_async

logger = logging.getLogger("trc8004_m2m.agent_protocol")


class AgentProtocolClient:
    """
    Agent Protocol standard client.
    
    Implements the Agent Protocol specification for A2A communication:
    - POST /ap/v1/agent/tasks: Create task
    - POST /ap/v1/agent/tasks/{task_id}/steps: Execute step
    
    Reference: https://agentprotocol.ai/
    
    Example:
        >>> client = AgentProtocolClient(
        ...     base_url="https://agent.example.com"
        ... )
        >>> result = await client.run({
        ...     "skill": "market_analysis",
        ...     "params": {"asset": "BTC/USDT"}
        ... })
    """
    
    def __init__(self, base_url: str, timeout: float = 30.0):
        """
        Initialize Agent Protocol client.
        
        Args:
            base_url: Agent service base URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        
        logger.info(f"AgentProtocolClient initialized: {base_url}")
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    @retry_async(operation_name="agent_protocol_create_task")
    async def create_task(self, input_text: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new task.
        
        Args:
            input_text: Optional initial input
        
        Returns:
            Task info dict with task_id
        
        Raises:
            NetworkError: If request fails
        
        Example:
            >>> task = await client.create_task()
            >>> print(task["task_id"])
            'abc123-...'
        """
        payload: Dict[str, Any] = {}
        if input_text is not None:
            payload["input"] = input_text
        
        try:
            response = await self.client.post(
                f"{self.base_url}/ap/v1/agent/tasks",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise NetworkError(f"Failed to create task: {e}")
    
    @retry_async(operation_name="agent_protocol_execute_step")
    async def execute_step(
        self,
        task_id: str,
        input_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a task step.
        
        Args:
            task_id: Task ID from create_task
            input_text: Step input (usually JSON string)
        
        Returns:
            Step result dict with output and status
        
        Raises:
            NetworkError: If request fails
        
        Example:
            >>> result = await client.execute_step(
            ...     task_id="abc123",
            ...     input_text='{"action": "quote"}'
            ... )
        """
        payload: Dict[str, Any] = {}
        if input_text is not None:
            payload["input"] = input_text
        
        try:
            response = await self.client.post(
                f"{self.base_url}/ap/v1/agent/tasks/{task_id}/steps",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise NetworkError(f"Failed to execute step: {e}")
    
    async def run(self, input_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        One-shot run: create task and execute.
        
        Convenience method that creates a task and executes one step.
        
        Args:
            input_payload: Input data dict (will be JSON serialized)
        
        Returns:
            Step execution result
        
        Raises:
            NetworkError: If task creation or execution fails
        
        Example:
            >>> result = await client.run({
            ...     "skill": "market_order",
            ...     "params": {
            ...         "asset": "TRX/USDT",
            ...         "amount": 100,
            ...     }
            ... })
            >>> print(result["output"])
        
        Note:
            Use this for simple single-step tasks.
            For complex multi-step tasks, use create_task and execute_step separately.
        """
        # Create task
        task = await self.create_task()
        task_id = task.get("task_id")
        if not task_id:
            raise NetworkError("No task_id in response")
        
        # Serialize input and execute
        input_text = json.dumps(input_payload, ensure_ascii=False)
        return await self.execute_step(task_id, input_text)
