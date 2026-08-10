"""Run this against your real registered agent_id on Shasta and paste the
output back — confirms the Agent record's real values in production use.

Usage:
    python inspect_agent.py <agent_id>
"""

import asyncio
import sys

from trc8004_m2m import AgentRegistry


async def main(agent_id: str):
    print(f"=== Inspecting agent_id={agent_id} on Shasta ===\n")

    registry = AgentRegistry(network="shasta", api_url="https://m2mregistry.io/api")

    try:
        exists = await registry.verify_agent_exists(agent_id=agent_id)
        print("verify_agent_exists():", exists)
    except Exception as exc:
        print("verify_agent_exists() raised:", repr(exc))
        return

    if not exists:
        print("Agent does not exist — nothing further to inspect.")
        return

    try:
        agent = await registry.get_agent(agent_id=agent_id)
        print("\nget_agent():")
        print(agent.model_dump_json(indent=2))
    except Exception as exc:
        print("get_agent() raised:", repr(exc))

    print("\n=== Done — paste this whole output back ===")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inspect_agent.py <agent_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
