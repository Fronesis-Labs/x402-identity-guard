# x402-identity-guard

**A pre-filter identity check for x402 servers, built on TRC-8004.**

TRC-8004 (m2mregistry.io) gives TRON three on-chain primitives for AI agents —
Identity, Reputation, Validation — but no single "is this agent OK" answer.
Every integrator has to interpret those primitives themselves.

`x402-identity-guard` is a reference policy layer that does that interpretation
for you, and returns one thing your server actually needs:

```
ALLOW | FLAG | DENY
```

## Where this fits

- **x402-identity-guard (this repo)** — pre-filter. "Should this agent be
  allowed to reach my server at all?" Cheap, fast, runs before any paid call.
- **[DCL Trust Oracle](https://github.com/Fronesis-Labs/dcl-webhook)** —
  post-filter. "Given that this agent is legitimate, is this specific action
  safe?" Full policy audit, tamper-evident log, x402-metered.

Run identity-guard first to reject spam/revoked agents for free, then spend
your DCL audit budget only on agents that pass.

## Status

Early. TRC-8004 / m2mregistry.io itself is early (mainnet + Shasta testnet,
registry currently near-empty). This ships a **fixed reference policy** for
v1 — not a configurable rules engine yet. See [Policy](#policy) below for
exactly what it checks, and [Roadmap](#roadmap) for what's next.

## Install

```bash
pip install x402-identity-guard   # not yet published — see Development below
```

## Quickstart

```python
from x402_identity_guard import resolve_trust

decision = await resolve_trust("agent_123")

if decision.status == "DENY":
    raise HTTPException(403, decision.reason)
elif decision.status == "FLAG":
    log_for_review(decision)
    # decide per your own risk tolerance whether FLAG still proceeds
```

### FastAPI middleware (for DCL-style servers)

```python
from fastapi import FastAPI
from x402_identity_guard.middleware import IdentityGuardMiddleware

app = FastAPI()
app.add_middleware(IdentityGuardMiddleware, agent_id_header="X-Agent-Id")
```

See `examples/dcl_integration_example.py` for wiring this in front of
`check_policy_before` / `check_policy_after`.

## Policy

v1's reference policy (`src/x402_identity_guard/policy.py`), in order:

1. No registered Identity on TRC-8004 → **DENY** (`no_identity`)
2. Latest Validation request has status `rejected` → **DENY** (`failed_validation`)
3. Reputation score below `REPUTATION_THRESHOLD` (default 50) → **FLAG** (`low_reputation`)
4. No Validation on record at all → **FLAG** (`unvalidated`)
5. Otherwise → **ALLOW**

These are constants at the top of `policy.py`, not a config file, by design —
see Roadmap. If your risk model differs, fork the function; it's ~30 lines.

## Roadmap

- v1 (this repo): fixed reference policy, Python only, TTL-cached registry reads
- v1.x: pluggable policy (swap `resolve_trust` for your own callable)
- Later, if there's real integrator demand: configurable thresholds
  (AND/OR/weighted signals), Node.js port

We're deliberately not building a rules-engine config format until someone
outside Fronesis Labs asks for one — guessing at requirements before any
integrator feedback isn't a good use of a 5-day sprint.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Registry client (`registry_client.py`) wraps the `trc8004-m2m` SDK behind a
small interface so the actual SDK call names can be corrected once verified
against live docs — see the `TODO` markers in that file.

## License

Apache 2.0
