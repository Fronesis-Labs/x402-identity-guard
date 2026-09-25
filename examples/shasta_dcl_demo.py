"""Smallest TRON-native Shasta demo. Local testnet example, not production.

Flow:
    TRC-8004 identity
    -> resolve_trust()
    -> DENY: stop
    -> ALLOW or FLAG: existing DCL evaluate_policy()
    -> ChainState.append() on a temporary SQLite file
    -> create_audit_event() (frozen Audit Event v1.0)
    -> print the canonical event JSON

Does not settle a payment, broadcast a TRON transaction, authenticate the
caller, spend TRON Energy or Bandwidth, use a relayer, or change DCL,
dcl-langchain, or the audit-event schema.

proof.tx_hash is the local SQLite hash-chain digest, not a TRON transaction.

Checkout layout, or the environment variables of the same names:

    workspace/
    ├── x402-identity-guard/
    ├── dcl-webhook/
    ├── dcl-core/
    └── dcl-audit-event/

    DCL_WEBHOOK_ROOT
    DCL_CORE_ROOT
    DCL_AUDIT_EVENT_ROOT

audit_logic imports yaml, so install PyYAML: pip install "pyyaml>=6.0.1"

Usage, from x402-identity-guard:
    python examples/shasta_dcl_demo.py
    python examples/shasta_dcl_demo.py 1:36
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

# examples/ is not a package; allow `python examples/shasta_dcl_demo.py`.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from x402_identity_guard.policy import Decision, resolve_trust
from x402_identity_guard.registry_client import RegistryClient

DEFAULT_AGENT_ID = "1:36"
SHASTA_RPC_URL = "https://api.shasta.trongrid.io"
# Fixed action text. The default DCL policy commits this string.
DEMO_ACTION = "The deployment finished and the service is healthy."
# Registry field consistency is not proof that the caller owns the agent.
IDENTITY_SOURCE = "trc8004_registry_read"
IDENTITY_CONFIDENCE = "unverified"


_REPO_ENV = {
    "dcl-webhook": "DCL_WEBHOOK_ROOT",
    "dcl-core": "DCL_CORE_ROOT",
    "dcl-audit-event": "DCL_AUDIT_EVENT_ROOT",
}


def _sibling_repo(name: str) -> Path:
    env_key = _REPO_ENV[name]
    override = os.environ.get(env_key)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / name


def _prepend_import_path(path: Path) -> None:
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def load_dcl_functions():
    """Import existing DCL functions without modifying those repositories."""
    webhook_root = _sibling_repo("dcl-webhook")
    core_root = _sibling_repo("dcl-core")
    audit_root = _sibling_repo("dcl-audit-event")
    located = (
        ("dcl-webhook", webhook_root),
        ("dcl-core", core_root),
        ("dcl-audit-event", audit_root),
    )
    missing = [(label, root) for label, root in located if not root.is_dir()]
    if missing:
        details = "\n".join(
            f"  {_REPO_ENV[label]}: {label} not found at {root}" for label, root in missing
        )
        raise FileNotFoundError(
            "Shasta demo could not find every DCL checkout.\n"
            "Set DCL_WEBHOOK_ROOT, DCL_CORE_ROOT, and DCL_AUDIT_EVENT_ROOT,\n"
            "or place dcl-webhook, dcl-core, and dcl-audit-event next to x402-identity-guard.\n"
            f"{details}"
        )
    _prepend_import_path(core_root)
    _prepend_import_path(audit_root)
    _prepend_import_path(webhook_root)

    try:
        import yaml  # audit_logic.evaluate_policy imports this lazily
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            'PyYAML is required because dcl-webhook audit_logic imports yaml. '
            'Install it with: pip install "pyyaml>=6.0.1" '
            "(also declared in dcl-webhook/requirements.txt)."
        ) from exc
    else:
        del yaml

    from audit_logic import BUILTIN_POLICIES, evaluate_policy
    from dcl_audit_event import SCHEMA_VERSION, create_audit_event
    from dcl_core import ChainState, sha256hex

    return {
        "BUILTIN_POLICIES": BUILTIN_POLICIES,
        "evaluate_policy": evaluate_policy,
        "create_audit_event": create_audit_event,
        "schema_version": SCHEMA_VERSION,
        "ChainState": ChainState,
        "sha256hex": sha256hex,
    }


def make_shasta_client() -> RegistryClient:
    """TRC-8004 reads against TRON Shasta. Testnet must be opted in."""
    return RegistryClient(
        network="shasta",
        allow_testnet=True,
        rpc_url=os.environ.get("TRON_SHASTA_RPC", SHASTA_RPC_URL),
        lookup_timeout_seconds=30.0,
    )


def build_audit_event(
    decision: Decision,
    *,
    verdict: str,
    policy_version: str,
    tx_hash: str,
    chain_index: int,
    create_audit_event: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if decision.status not in {"ALLOW", "FLAG"}:
        raise ValueError("audit events are only built after ALLOW or FLAG")
    return create_audit_event(
        service="x402-identity-guard",
        producer="shasta-dcl-demo",
        route="examples/shasta_dcl_demo.py",
        agent_id=decision.agent_id,
        identity_source=IDENTITY_SOURCE,
        identity_confidence=IDENTITY_CONFIDENCE,
        task_type="shasta_demo",
        policy_id="default",
        policy_version=policy_version,
        verdict=verdict,
        proof={"tx_hash": tx_hash, "chain_index": chain_index},
        integration={"name": "x402-identity-guard", "network": "shasta"},
        metadata={
            "identity_status": decision.status,
            "identity_reason": decision.reason,
            "note": (
                "identity_confidence records a TRC-8004 registry read only; "
                "the caller was not authenticated"
            ),
        },
    )


async def run_demo(
    agent_id: str = DEFAULT_AGENT_ID,
    *,
    action: str = DEMO_ACTION,
    db_path: str | None = None,
    client: RegistryClient | None = None,
    resolve: Callable[..., Awaitable[Decision]] = resolve_trust,
    dcl: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Run one demo pass.

    Returns the canonical audit event, or None when identity policy denies
    the agent before DCL runs.
    """
    decision = await resolve(agent_id, client=client)
    if decision.status == "DENY" or decision.record is None:
        return None
    if decision.status not in {"ALLOW", "FLAG"}:
        raise RuntimeError(f"unexpected identity status: {decision.status}")

    loaded = dcl or load_dcl_functions()
    policy_yaml = loaded["BUILTIN_POLICIES"]["default"]
    verdict, confidence, reason, policy_version = loaded["evaluate_policy"](action, policy_yaml)
    sha256hex = loaded["sha256hex"]
    input_hash = "0x" + sha256hex(action)[:16]
    policy_hash = sha256hex(policy_yaml)[:16]

    owns_db = db_path is None
    if owns_db:
        handle = tempfile.NamedTemporaryFile(prefix="shasta-dcl-", suffix=".db", delete=False)
        handle.close()
        db_path = handle.name

    chain = loaded["ChainState"](db_path)
    try:
        tx_hash, chain_index = chain.append(
            verdict=verdict,
            input_hash=input_hash,
            policy_hash=policy_hash,
            agent_id=decision.agent_id,
            reason=reason,
            confidence=confidence,
            task_type="shasta_demo",
        )
    finally:
        connection = getattr(chain, "_conn", None)
        if connection is not None:
            connection.close()
        if owns_db:
            Path(db_path).unlink(missing_ok=True)

    return build_audit_event(
        decision,
        verdict=verdict,
        policy_version=policy_version,
        tx_hash=tx_hash,
        chain_index=chain_index,
        create_audit_event=loaded["create_audit_event"],
    )


def write_event(path: str | Path, event: dict[str, Any]) -> None:
    """Write one frozen v1.0 event for the Transparency Board exporter."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(event, indent=2) + "\n", encoding="utf-8")


def _print_deny(decision: Decision) -> None:
    print(
        json.dumps(
            {
                "stopped": True,
                "reason": "identity check stopped before DCL; policy was not evaluated",
                "agent_id": decision.agent_id,
                "identity_status": decision.status,
                "identity_reason": decision.reason,
            },
            indent=2,
        )
    )


async def _main(agent_id: str, event_out: str | None = None) -> int:
    client = make_shasta_client()
    decision = await resolve_trust(agent_id, client=client)
    if decision.status == "DENY" or decision.record is None:
        _print_deny(decision)
        return 0
    event = await run_demo(agent_id, client=client, resolve=_return(decision))
    print(json.dumps(event, indent=2))
    if event_out:
        write_event(event_out, event)
        print(f"wrote {event_out}", file=sys.stderr)
    return 0


def _return(decision: Decision):
    async def _resolve(agent_id: str, client: RegistryClient | None = None) -> Decision:
        return decision

    return _resolve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TRON Shasta identity to DCL audit-event demo")
    parser.add_argument("agent_id", nargs="?", default=DEFAULT_AGENT_ID)
    parser.add_argument(
        "--event-out",
        default=None,
        help="Write the canonical event JSON here for the Transparency Board exporter",
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_main(args.agent_id, event_out=args.event_out))
    except Exception as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
