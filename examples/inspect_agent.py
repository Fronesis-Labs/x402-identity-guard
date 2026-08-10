"""Run this against a real agent_id on Shasta and print the full evaluation.

Usage:
    python inspect_agent.py <chainId:tokenId or bare tokenId>

Example (the project's own confirmed live test agent):
    python inspect_agent.py 1:36
"""

import asyncio
import sys

from x402_identity_guard.policy import resolve_trust


async def main(agent_id: str):
    decision = await resolve_trust(agent_id)

    print("=" * 60)
    print(f"IDENTITY-GUARD EVALUATION: {agent_id}")
    print("=" * 60)
    print(f"Status      : {decision.status}")
    print(f"Reason      : {decision.reason}")
    print(f"Agent ID    : {decision.agent_id}")

    record = decision.record
    if record is not None:
        identity = record.identity
        signals = record.trust_signals
        print("\n--- IDENTITY ---")
        print(f"Owner       : {identity.owner}")
        print(f"Wallet      : {identity.wallet}")
        print(f"Consistent  : {identity.is_consistent}")
        print(f"Metadata W. : {identity.metadata_wallet}")
        print("\n--- CLASSIFICATION ---")
        print(f"Class       : {record.classification.value}")
        print("\n--- TRUST SIGNALS ---")
        print(f"Reputation  : {signals.reputation_average_value} (Count: {signals.reputation_count})")
        print(f"Validation  : {signals.validation_summary}")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inspect_agent.py <agent_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
