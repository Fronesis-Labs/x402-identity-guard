"""FastAPI middleware wrapper.

Kept separate from policy.py so resolve_trust() stays framework-agnostic
and usable from plain scripts, MCP tool handlers, etc.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .policy import resolve_trust
from .registry_client import RegistryClient


class IdentityGuardMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        agent_id_header: str = "X-Agent-Id",
        block_on_flag: bool = False,
        client: RegistryClient | None = None,
    ):
        super().__init__(app)
        self._header = agent_id_header
        self._block_on_flag = block_on_flag
        self._client = client

    async def dispatch(self, request: Request, call_next):
        agent_id = request.headers.get(self._header)
        if agent_id is None:
            # No agent header at all — not this middleware's call to make.
            # Let the request through; your route can require the header itself.
            return await call_next(request)

        decision = await resolve_trust(agent_id, client=self._client)

        if decision.status == "DENY":
            return JSONResponse(
                status_code=403,
                content={"error": "agent_denied", "reason": decision.reason},
            )

        if decision.status == "FLAG" and self._block_on_flag:
            return JSONResponse(
                status_code=423,
                content={"error": "agent_flagged", "reason": decision.reason},
            )

        request.state.identity_decision = decision
        return await call_next(request)
