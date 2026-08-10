# x402-identity-guard

**A pre-filter identity check for x402 servers, built on TRC-8004.**

TRC-8004 gives TRON on-chain primitives for AI agents — Identity (as an
NFT), Reputation (client feedback with an averaged score), Validation
(third-party attestations) — but no single "is this agent OK" answer.
Every integrator has to interpret those primitives themselves.

`x402-identity-guard` is a reference policy layer that does that
interpretation for you, and returns one thing your server actually needs:

```
ALLOW | FLAG | DENY
```

## Where this fits

- **x402-identity-guard (this repo)** — pre-filter. "Should this agent be
  allowed to reach my server at all?" Cheap, fast, runs before any paid call.
- **[DCL Trust Oracle](https://github.com/Fronesis-Labs/dcl-webhook)** —
  post-filter. "Given that this agent is legitimate, is this specific action
  safe?" Full policy audit, tamper-evident log, x402-metered.

Run identity-guard first to reject spam/unregistered agents for free, then
spend your DCL audit budget only on agents that pass.

```
                 ┌──────────────┐
                 │ Identity     │
                 │ on-chain     │
                 └──────┬───────┘
                        │
              ┌─────────┼─────────┐
              ▼         ▼         ▼
           owner     wallet    tokenURI
              │         │         │
              └────┬────┘         ▼
                   │          metadata
                   ▼
             CONSISTENCY
                   │
          ┌────────┴────────┐
          ▼                 ▼
      Reputation        Validation
          │                 │
          └────────┬────────┘
                   ▼
              Trust Policy
                   │
             ALLOW/FLAG/DENY
```

## Status

Built on [BofAI/8004-sdk](https://github.com/BofAI/8004-sdk) and
[BofAI/trc-8004-contracts](https://github.com/BofAI/trc-8004-contracts) —
the actively maintained TRC-8004 implementation on TRON. An earlier version
of this project targeted `trc8004-m2m` / m2mregistry.io, which turned out
to be an abandoned, unmaintained fork of the same standard (dead site,
broken SDK defaults, unreachable API — see git history for the debugging
trail if you're curious). Everything below reflects the current,
BofAI-based implementation, confirmed working against a real registered
agent on Shasta testnet.

Reads go directly to the chain (`ownerOf`, `getAgentWallet`, `tokenURI`,
`getMetadata`, `getClients`, `getReputationSummary`, `getAgentValidations`)
via `bankofai.sdk_8004` — no separate indexed API to depend on, no API
outages to work around.

## Install

```bash
pip install starlette tronpy
pip install "git+https://github.com/BofAI/8004-sdk.git#subdirectory=python"
```

## Quickstart

```python
from x402_identity_guard import resolve_trust

decision = await resolve_trust("1:36")  # chainId:tokenId

if decision.status == "DENY":
    raise HTTPException(403, decision.reason)
elif decision.status == "FLAG":
    log_for_review(decision)
```

### FastAPI middleware

```python
from fastapi import FastAPI
from x402_identity_guard.middleware import IdentityGuardMiddleware

app = FastAPI()
app.add_middleware(IdentityGuardMiddleware, agent_id_header="X-Agent-Id")
```

See `examples/dcl_integration_example.py` for wiring this in front of
DCL's `check_policy_before` / `check_policy_after`, and
`examples/inspect_agent.py` for a full evaluation printout on a real
agent_id.

## Policy

Reference policy (`src/x402_identity_guard/policy.py`), evaluated in order:

1. Identity doesn't exist on-chain → **DENY** (`no_identity`)
2. Owner / wallet / metadata-declared wallet don't all match → **DENY** (`inconsistent_identity`) — a cryptographic invariant check, not a reputation judgment
3. Any validation on record that isn't positive → **DENY** (`failed_validation`)
4. Reputation average below `MIN_REPUTATION_SCORE` (default 50, on the contract's own 0-100 scale) → **DENY** (`low_reputation_score`)
5. Registered and consistent, but no reputation or validation history yet → **FLAG** (`known_but_untrusted`)
6. Off-chain registration file (agentURI) unreachable → **FLAG** (`unreachable_registration_file`)
7. Otherwise → **ALLOW**

`MIN_REPUTATION_SCORE` is a constant at the top of `policy.py`, not a
config file, by design — see Roadmap. It's our own reasonable-looking
default, not derived from any TRC-8004 spec — revisit once real agents
have real feedback history. If your risk model differs, fork
`_decide()`; it's short on purpose.

## Roadmap

- v1 (this repo): fixed reference policy, on-chain reads only, TTL-cached
- v1.x: pluggable policy (swap `resolve_trust` for your own callable)
- Later, if there's real integrator demand: configurable/weighted
  thresholds, Node.js port

We're deliberately not building a rules-engine config format or a second
language port until someone outside Fronesis Labs actually asks for one.

## Development

```bash
pip install -e ".[dev]"
pip install tronpy
pytest
```

## License

Apache 2.0
