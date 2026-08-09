"""Run this against your real registered agent_id on Shasta and paste the
output back — this settles the AgentRecord shape from fact, not guesses.

Usage:
    python inspect_agent.py <agent_id>
"""

import asyncio
import sys

from trc8004_m2m import AgentRegistry, RegistryAPI


async def main(agent_id: str):
    print(f"=== Inspecting agent_id={agent_id} on Shasta ===\n")

    # --- On-chain, read-only (no private_key needed) ---
    chain = AgentRegistry(network="shasta")
    print("--- AgentRegistry (on-chain) ---")
    try:
        agent = await chain.get_agent(agent_id=agent_id)
        print("get_agent():", repr(agent))
    except Exception as exc:
        print("get_agent() raised:", repr(exc))

    # --- Indexed API (fast path) ---
    api = RegistryAPI(base_url="https://m2mregistry.io/api")
    print("\n--- RegistryAPI (indexed) ---")
    try:
        agent = await api.get_agent(agent_id=agent_id)
        print("get_agent():", repr(agent))
    except Exception as exc:
        print("get_agent() raised:", repr(exc))

    try:
        reputation = await api.get_reputation(agent_id=agent_id)
        print("get_reputation():", repr(reputation))
    except Exception as exc:
        print("get_reputation() raised:", repr(exc))

    try:
        validation = await api.get_validation_stats(agent_id=agent_id)
        print("get_validation_stats():", repr(validation))
    except Exception as exc:
        print("get_validation_stats() raised:", repr(exc))

    print("\n=== Done — paste this whole output back ===")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inspect_agent.py <agent_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
