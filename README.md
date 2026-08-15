# x402-identity-guard

[![CI](https://github.com/Fronesis-Labs/x402-identity-guard/actions/workflows/ci.yml/badge.svg )](https://github.com/Fronesis-Labs/x402-identity-guard/actions/workflows/ci.yml )
[![TRC-8004](https://img.shields.io/badge/TRON-TRC--8004-1677ff.svg )](https://github.com/BofAI/trc-8004-contracts )
[![License](https://img.shields.io/github/license/Fronesis-Labs/x402-identity-guard )](LICENSE)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-3776ab.svg )](https://www.python.org/ )


**An open-source trust gateway for agent-facing services on TRON, built on TRC-8004.**

> **Status:** pre-release hardened reference implementation. The `main` branch is the current development target for `v0.3.0`; no tagged stable release has been published yet.

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
  allowed to reach my protected endpoint at all?" It is designed to run before
  protected execution and may reduce unnecessary downstream or paid work, but
  it does not guarantee that an x402 payment is prevented unless deployed
  before the payment/facilitation boundary.
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
      REGISTRY CONSISTENCY CHECK
       (not caller authentication)
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
agent on Shasta testnet. This is testnet evidence, not a claim of mainnet
production readiness; mainnet validation is a separate release milestone.

Reads go directly to the configured registry through
`bankofai.sdk_8004` (`ownerOf`, `getAgentWallet`, `tokenURI`, `getMetadata`,
`getClients`, `getReputationSummary`, `getAgentValidations`) rather than
requiring a separate indexed API. The service still depends on the configured
RPC endpoint, registry contracts, SDK and off-chain registration files; those
dependencies can be unavailable or return stale data.

## Install

```bash
pip install starlette tronpy
pip install "git+https://github.com/BofAI/8004-sdk.git#subdirectory=python"
```

The command above is suitable for development. Before production use, pin the
BofAI SDK to a reviewed commit and lock the transitive dependencies. The
current pre-release does not yet ship a production lockfile.

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
app.add_middleware(
    IdentityGuardMiddleware,
    agent_id_header="X-Agent-Id",
    protected_paths={"/paid/tool"},
    block_on_flag=True,
    fail_closed_on_registry_error=True,
)
```

`protected_paths` uses exact path matching. A missing `X-Agent-Id` header
continues through public routes, but returns `401` on protected routes. With
`block_on_flag=True`, a flagged protected request returns `423`; registry
failures return `503` when `fail_closed_on_registry_error=True`.

The middleware does not authenticate the caller or bind `X-Agent-Id` to an
x402 payer by itself. For authorization-sensitive deployments, provide an
`identity_binding` callback that verifies the caller, payer or delegation.
See `examples/dcl_integration_example.py` for wiring this in front of
DCL's `check_policy_before` / `check_policy_after`, and
`examples/inspect_agent.py` for a full evaluation printout on a real
agent_id.

## Policy

Reference policy (`src/x402_identity_guard/policy.py`), evaluated in order:

1. Identity is not found by the configured registry → **DENY** (`no_identity`). An ambiguous RPC/registry failure is not treated as proof of non-existence; protected middleware routes fail closed with `503` by default.
2. Required registry fields are missing or the optional metadata wallet does not match the registered wallet → **DENY** (`inconsistent_identity`). This is a registry-field consistency check, not proof that the caller owns the agent or that `owner == wallet` cryptographically.
3. A validation status fails the configured pass rule → **DENY** (`failed_validation`). The validation response-score semantics must match the deployed BofAI/TRC-8004 ABI.
4. Reputation average below `MIN_REPUTATION_SCORE` → **DENY** (`low_reputation_score`). The reference policy currently assumes a deployment-specific 0–100 feedback scale; TRC-8004 does not make that scale universal.
5. Registered and consistent, but no reputation or validation history yet → **FLAG** (`known_but_untrusted`).
6. Off-chain registration file (agentURI) unreachable → **FLAG** (`unreachable_registration_file`).
7. Otherwise → **ALLOW**. `ALLOW` means that the available data satisfied this policy; it does not prove that the agent is safe or authorized for every action.

`MIN_REPUTATION_SCORE` is a constant at the top of `policy.py`, not a
config file. It is a reference-policy assumption, not a TRC-8004 security
requirement. Because feedback is not protocol-enforced to a universal scale,
deployments should normalize and version their reputation policy before using
this threshold for high-impact authorization.

### Swapping in your own policy

`resolve_trust` and `IdentityGuardMiddleware` both accept an optional
`policy` callable — `AgentRecord -> Decision` — instead of forking the
package. The reference policy above (`default_policy` in `policy.py`)
is used if you don't pass one:

```python
from x402_identity_guard import resolve_trust
from x402_identity_guard.policy import Decision
from x402_identity_guard.registry_client import AgentRecord

def lenient_policy(record: AgentRecord) -> Decision:
    """Only DENY on registry-field inconsistency; FLAG everything else."""
    if not record.identity.is_consistent:
        return Decision("DENY", "inconsistent_identity", record.identity.agent_id, record)
    return Decision("ALLOW", "ok", record.identity.agent_id, record)

decision = await resolve_trust("1:36", policy=lenient_policy)
```

Same pattern with the middleware:

```python
app.add_middleware(IdentityGuardMiddleware, policy=lenient_policy)
```

`default_policy` is still importable and callable directly if you want
to reuse most of it and only override a piece — it's short on purpose.
(`_decide` is kept as a backwards-compatible alias for `default_policy`.)

## Current status and roadmap

### Current development target

- Hardened reference middleware and registry client on the `main` branch.
- Pluggable policy support is implemented through the `policy` argument.
- Testnet validation has been performed against a real registered agent on
  Shasta; mainnet validation and live integration evidence remain separate
  release milestones.
- A tagged stable release has not yet been published.

### Next milestones

- Pin the reviewed BofAI SDK commit and add CI dependency/security checks.
- Confirm `getValidationStatus()` semantics against the deployed mainnet ABI.
- Publish reproducible mainnet/network validation and latency evidence.
- Align reputation-scale assumptions with real feedback sources and version the
  policy thresholds.
- Publish a stable `v0.3.0` release with migration notes and protected-route
  integration examples.
- Add configurable/weighted thresholds and a Node.js/TypeScript integration
  only after validated demand from external integrators.

The project deliberately avoids presenting roadmap work as implemented
security guarantees.

## Development

```bash
pip install -e ".[dev]"
pip install tronpy
python -m pytest -q
```

## Security

See [SECURITY.md](SECURITY.md) for the current security policy, threat model,
known limitations, vulnerability reporting process and production deployment
requirements.

## License

Apache 2.0
