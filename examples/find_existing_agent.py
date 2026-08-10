"""Search for any existing registered agent on Shasta — read-only,
no private key needed.

api_url is passed explicitly: trc8004-m2m's AgentRegistry defaults
api_url to http://localhost:8000, which is not m2mregistry.io's real
API — confirmed against their own docs (m2mregistry.io/docs/api,
"Base URL: https://m2mregistry.io/api"). Without this override every
API-backed call (search_agents, and — per registry_client.py's
get_agent()/verify_agent_exists()) fails with a connection error.
"""

import asyncio

from trc8004_m2m import AgentRegistry

REAL_API_URL = "https://m2mregistry.io/api"


async def main():
    registry = AgentRegistry(network="shasta", api_url=REAL_API_URL)
    try:
        agents = await registry.search_agents(query="")
        print("search_agents() result:")
        print(agents)
    except Exception as exc:
        print("search_agents() raised:", repr(exc))


if __name__ == "__main__":
    asyncio.run(main())
