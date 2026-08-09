"""How x402-identity-guard sits in front of a DCL-style audit endpoint.

Pattern: identity-guard is the free/cheap pre-filter. DCL's paid x402
audit only runs for agents that pass. This is illustrative — wire the
actual DCL call into your real dcl-webhook client.
"""

from fastapi import FastAPI, HTTPException, Request

from x402_identity_guard import resolve_trust

app = FastAPI()


async def call_dcl_check_policy_before(agent_id: str, action_context: dict):
    """Stand-in for the real dcl-webhook client call."""
    raise NotImplementedError("wire this up to your dcl_webhook client")


@app.post("/audit/check_policy_before")
async def check_policy_before(request: Request):
    agent_id = request.headers.get("X-Agent-Id")
    if agent_id is None:
        raise HTTPException(400, "missing X-Agent-Id header")

    decision = await resolve_trust(agent_id)

    if decision.status == "DENY":
        # Rejected before any paid DCL audit call — this is the whole point.
        raise HTTPException(403, f"agent denied: {decision.reason}")

    if decision.status == "FLAG":
        # Your call: still allow through to DCL but log it, or block here too.
        # This example allows through with a logged flag.
        print(f"[identity-guard] FLAG agent={agent_id} reason={decision.reason}")

    action_context = await request.json()
    return await call_dcl_check_policy_before(agent_id, action_context)
