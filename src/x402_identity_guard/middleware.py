"""Security-conscious Starlette middleware for x402 Identity Guard.

The middleware is intentionally explicit about protected routes. A globally
installed middleware must not silently turn every route into an agent-only route,
but protected routes must not silently accept missing or unauthenticated identity.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .policy import Decision, PolicyFn, resolve_trust
from .registry_client import AgentIdError, RegistryClient, RegistryError, normalize_agent_id


IdentityBinding = Callable[[Request, str], bool | Awaitable[bool]]


class IdentityGuardMiddleware(BaseHTTPMiddleware):
    """Apply identity/trust policy before a downstream Starlette route.

    Secure integration example::

        app.add_middleware(
            IdentityGuardMiddleware,
            client=client,
            protected_paths={"/paid/tool", "/wallet/transfer"},
            require_identity_binding=True,
            identity_binding=verify_agent_to_payer_binding,
            block_on_flag=True,
            fail_closed_on_registry_error=True,
        )

    ``protected_paths`` uses exact path matching. ``require_agent_id=True`` can
    protect all routes except ``exempt_paths``. Public routes may still be
    evaluated when a valid header is supplied, but are never blocked for a
    missing header unless they are explicitly protected.
    """

    def __init__(
        self,
        app: Any,
        agent_id_header: str = "X-Agent-Id",
        block_on_flag: bool = False,
        client: RegistryClient | None = None,
        policy: PolicyFn | None = None,
        *,
        require_agent_id: bool = False,
        protected_paths: Iterable[str] | None = None,
        exempt_paths: Iterable[str] | None = None,
        require_identity_binding: bool = False,
        identity_binding: IdentityBinding | None = None,
        fail_closed_on_registry_error: bool = True,
        fail_closed_on_internal_error: bool = True,
        max_agent_id_length: int = 128,
    ) -> None:
        super().__init__(app)

        if not isinstance(agent_id_header, str) or not agent_id_header:
            raise ValueError("agent_id_header must be a non-empty string")
        if any(char in agent_id_header for char in "\r\n:"):
            raise ValueError("agent_id_header contains forbidden characters")
        if not isinstance(block_on_flag, bool):
            raise ValueError("block_on_flag must be bool")
        if not isinstance(require_agent_id, bool):
            raise ValueError("require_agent_id must be bool")
        if not isinstance(require_identity_binding, bool):
            raise ValueError("require_identity_binding must be bool")
        if not isinstance(fail_closed_on_registry_error, bool):
            raise ValueError("fail_closed_on_registry_error must be bool")
        if not isinstance(fail_closed_on_internal_error, bool):
            raise ValueError("fail_closed_on_internal_error must be bool")
        if not isinstance(max_agent_id_length, int) or not 1 <= max_agent_id_length <= 4096:
            raise ValueError("invalid max_agent_id_length")
        if require_identity_binding and identity_binding is None:
            raise ValueError(
                "identity_binding is required when require_identity_binding=True"
            )
        if identity_binding is not None and not callable(identity_binding):
            raise ValueError("identity_binding must be callable")

        self._header = agent_id_header
        self._block_on_flag = block_on_flag
        self._require_agent_id = require_agent_id
        self._protected_paths = self._normalize_paths(protected_paths or ())
        self._exempt_paths = self._normalize_paths(exempt_paths or ())
        self._require_identity_binding = require_identity_binding
        self._identity_binding = identity_binding
        self._fail_closed_on_registry_error = fail_closed_on_registry_error
        self._fail_closed_on_internal_error = fail_closed_on_internal_error
        self._max_agent_id_length = max_agent_id_length
        self._client = client
        self._policy = policy

    @staticmethod
    def _normalize_paths(paths: Iterable[str]) -> frozenset[str]:
        normalized: set[str] = set()
        for path in paths:
            if not isinstance(path, str) or not path.startswith("/") or "\r" in path or "\n" in path:
                raise ValueError("paths must be absolute paths without control characters")
            normalized.add(path)
        return frozenset(normalized)

    def _is_protected(self, request: Request) -> bool:
        path = request.url.path
        if path in self._exempt_paths:
            return False
        return self._require_agent_id or path in self._protected_paths

    def _json_error(self, status_code: int, error: str, reason: str) -> JSONResponse:
        # Reasons are generated from stable internal codes. Bound them even for
        # custom policies so a malformed policy cannot create huge responses.
        safe_reason = str(reason).replace("\r", " ").replace("\n", " ")[:256]
        response = JSONResponse(
            status_code=status_code,
            content={"error": error, "reason": safe_reason},
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def _default_chain_id(self) -> int:
        if self._client is not None:
            configured = getattr(self._client, "default_chain_id", None)
            if isinstance(configured, int):
                return configured
        return 1

    def _read_single_agent_header(self, request: Request) -> str | None:
        header_name = self._header.lower().encode("ascii")
        values = [
            value.decode("latin-1")
            for name, value in request.scope.get("headers", [])
            if name.lower() == header_name
        ]
        if len(values) > 1:
            raise AgentIdError("duplicate_agent_id_header")
        return values[0] if values else None

    def _canonicalize_header(self, raw_agent_id: str) -> str:
        if not isinstance(raw_agent_id, str):
            raise AgentIdError("invalid_agent_id")
        if len(raw_agent_id) > self._max_agent_id_length:
            raise AgentIdError("invalid_agent_id")
        canonical, _ = normalize_agent_id(
            raw_agent_id,
            self._default_chain_id(),
            max_length=self._max_agent_id_length,
        )
        return canonical

    async def _verify_binding(self, request: Request, canonical_agent_id: str) -> bool:
        if self._identity_binding is None:
            return False
        try:
            result = self._identity_binding(request, canonical_agent_id)
            if inspect.isawaitable(result):
                result = await result
            return result is True
        except Exception:
            # Binding failures are deliberately not exposed to the caller.
            return False

    @staticmethod
    def _is_registry_error(decision: Decision) -> bool:
        return decision.reason.startswith("registry_")

    def _decision_is_consistent(self, decision: Decision, canonical_agent_id: str) -> bool:
        if decision.status not in {"ALLOW", "FLAG", "DENY"}:
            return False
        if decision.record is None:
            return self._is_registry_error(decision)
        return (
            decision.agent_id == canonical_agent_id
            and decision.record.identity.agent_id == canonical_agent_id
        )

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        protected = self._is_protected(request)
        try:
            raw_agent_id = self._read_single_agent_header(request)
        except AgentIdError as exc:
            return self._json_error(400, "invalid_agent_identity", str(exc))

        if raw_agent_id is None:
            if protected:
                return self._json_error(401, "agent_identity_required", "missing_agent_id")
            return await call_next(request)

        try:
            canonical_agent_id = self._canonicalize_header(raw_agent_id)
        except AgentIdError as exc:
            return self._json_error(400, "invalid_agent_identity", str(exc))

        if protected and self._require_identity_binding:
            if not await self._verify_binding(request, canonical_agent_id):
                return self._json_error(401, "agent_identity_unverified", "identity_binding_failed")
            request.state.identity_binding_verified = True
        else:
            request.state.identity_binding_verified = False

        try:
            decision = await resolve_trust(
                canonical_agent_id,
                client=self._client,
                policy=self._policy,
            )
        except AgentIdError as exc:
            return self._json_error(400, "invalid_agent_identity", str(exc))
        except RegistryError:
            if protected and self._fail_closed_on_registry_error:
                return self._json_error(503, "identity_verification_unavailable", "registry_unavailable")
            return await call_next(request)
        except Exception:
            if protected and self._fail_closed_on_internal_error:
                return self._json_error(503, "identity_verification_failed", "internal_verification_error")
            return await call_next(request)

        if not self._decision_is_consistent(decision, canonical_agent_id):
            if protected and self._fail_closed_on_internal_error:
                return self._json_error(503, "identity_verification_failed", "inconsistent_verification_result")
            return await call_next(request)

        if decision.status == "DENY":
            return self._json_error(403, "agent_denied", decision.reason)

        if decision.status == "FLAG":
            if self._is_registry_error(decision):
                if protected and self._fail_closed_on_registry_error:
                    return self._json_error(503, "identity_verification_unavailable", "registry_unavailable")
            elif protected and self._block_on_flag:
                return self._json_error(423, "agent_flagged", decision.reason)

        # Only expose a decision to downstream code after the decision and its
        # agent-id binding have passed consistency checks. The downstream route
        # remains responsible for action authorization.
        request.state.identity_decision = decision
        request.state.identity_agent_id = canonical_agent_id
        request.state.identity_verified = decision.status == "ALLOW"
        return await call_next(request)
