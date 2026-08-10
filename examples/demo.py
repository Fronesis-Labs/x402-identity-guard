"""DCL / x402 Identity Guard trust demo.

Usage:
    python examples/demo.py 1:36
"""

import asyncio
import sys

from x402_identity_guard.policy import resolve_trust


def checkmark(value: bool) -> str:
    return "✓" if value else "✗"


async def main(agent_id: str) -> None:
    decision = await resolve_trust(agent_id)

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║          DCL / x402 AGENT TRUST CHECK            ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    print(f"Agent:   {decision.agent_id}")
    print("Network: TRON Shasta")
    print()

    record = decision.record

    if record is None:
        print("IDENTITY")
        print("  ✗ Agent could not be resolved")
        print()
        print("VERDICT")
        print(f"  {decision.status}")
        print(f"  {decision.reason}")
        return

    identity = record.identity
    signals = record.trust_signals

    print("IDENTITY")
    print(f"  {checkmark(identity.owner is not None)} On-chain identity")
    print(
        f"  {checkmark(identity.owner == identity.wallet)} "
        "Owner / wallet consistent"
    )
    print(
        f"  {checkmark(identity.metadata_wallet == identity.wallet)} "
        "Metadata consistent"
    )

    print()
    print("TRUST EVIDENCE")

    reputation_ok = signals.reputation_count > 0
    validation_ok = signals.validation_count > 0

    print(
        f"  {checkmark(reputation_ok)} "
        f"Reputation: {signals.reputation_count} record(s)"
    )
    print(
        f"  {checkmark(validation_ok)} "
        f"Validation: {signals.validation_count} record(s)"
    )

    print()
    print("──────────────────────────────────────────────────")

    status = str(decision.status)
    classification = record.classification.value

    print(f"VERDICT:       {status}")
    print(f"CLASSIFICATION: {classification}")
    print(f"REASON:        {decision.reason}")

    print("──────────────────────────────────────────────────")

    if classification == "KNOWN_BUT_UNTRUSTED":
        print()
        print("⚠ This agent has a valid identity,")
        print("  but insufficient trust evidence.")
        print()
        print("→ Do not automatically allow a paid action.")
        print("→ Escalate to deeper verification.")

    elif status == "ALLOW":
        print()
        print("✓ Trust requirements satisfied.")
        print("→ Agent may proceed.")

    elif status == "DENY":
        print()
        print("⛔ Agent failed the trust policy.")
        print("→ Action should be blocked.")

    print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python examples/demo.py <agent_id>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))