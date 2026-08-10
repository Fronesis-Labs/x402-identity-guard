"""Register a test agent on TRC-8004 (Shasta testnet).

SECURITY: paste your private key into the PRIVATE_KEY environment
variable, never into this file directly. Never commit a private key
to git, even a testnet-only one.

    export PRIVATE_KEY="your_key_here"   # git bash / macOS / Linux
    python register_test_agent.py

Uses register_agent() — confirmed via inspect.signature() +
__doc__ against a live install (2026-08-09):
    register_agent(name: str, description: str, skills=None,
                    endpoints=None, tags=None, version='1.0.0') -> int
It builds metadata JSON, uploads to IPFS, computes a keccak256 hash,
calls IdentityRegistry.register() on-chain, and parses agent_id from
the transaction events. Returns an int agent_id.

(register_agent_simple() was NOT what we want here — its docstring
says "Register a blank agent (ERC-8004 no-arg overload)": no name/
description at all.)
"""

import asyncio
import os

from trc8004_m2m import AgentRegistry


async def main():
    private_key = os.environ.get("PRIVATE_KEY")
    if not private_key:
        raise SystemExit("Set the PRIVATE_KEY environment variable first (see docstring).")

    registry = AgentRegistry(network="shasta", private_key=private_key, api_url="https://m2mregistry.io/api")

    print("Registering agent...")
    agent_id = await registry.register_agent(
        name="x402-identity-guard test agent",
        description="Test agent for identity-guard integration testing",
    )
    print(f"\nRegistered! agent_id = {agent_id}")
    print("Save this agent_id — you'll need it for inspect_agent.py")


if __name__ == "__main__":
    asyncio.run(main())
