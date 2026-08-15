# Security Policy

Last updated: 2026-08-15 (v0.3.0-pre)

## Overview

`x402 Identity Guard` is a pre-request identity and trust gate for x402-enabled
services on TRON. It evaluates TRC-8004 identity, wallet, reputation, and
validation signals before an incoming AI-agent request reaches a protected
endpoint, and returns one of three policy decisions: `ALLOW`, `FLAG`, or `DENY`.

It is a **policy enforcement point**, not a proof that an agent is safe. It does
not verify that an agent's software is benign, that its declared capabilities
are truthful, or that it cannot become compromised after a decision is made.
Reduce exposure to unknown or low-trust agents before a paid or sensitive
operation runs — that is the whole job of this project, not a general-purpose
authorization system.

## Supported Versions

| Version | Supported | Notes |
|---|---|---|
| main (unreleased, hardened middleware/registry_client) | Yes | Current development target for v0.3.0 |
| 0.2.x | No | Predates fail-closed enforcement mode; upgrade recommended |

This project does not yet have a tagged release. Until v0.3.0 ships, "supported"
means the `main` branch.

## Reporting a Vulnerability

Please do not open a public GitHub issue for a suspected vulnerability.

- **Preferred:** open a [GitHub Security Advisory](https://github.com/Fronesis-Labs/x402-identity-guard/security/advisories/new) (private to maintainers until published).
- **Alternative:** email security@fronesislabs.com with a description, affected
  component/version, reproduction steps, and potential impact.

We aim to acknowledge reports within **5 business days** and to provide an
initial assessment (confirmed / not applicable / need more info) within **10
business days**. Fix timelines depend on severity — critical fail-open or
identity-spoofing issues are prioritized above all other work. Please allow
**90 days** from acknowledgment before public disclosure, or coordinate an
earlier date with us if there's active exploitation.

## Fail-Safe Behavior (as actually implemented)

This is the concrete, current behavior of `IdentityGuardMiddleware` and
`RegistryClient` — not aspirational language.

| Situation | Response |
|---|---:|
| No `X-Agent-Id` header, route not protected | Request passes through |
| No `X-Agent-Id` header, route protected (`protected_paths` or `require_agent_id=True`) | `401` |
| Duplicate or malformed `X-Agent-Id` header | `400` |
| Identity binding required but not verified | `401` |
| Registry unavailable or timed out, protected route | `503` (if `fail_closed_on_registry_error=True`, the default) |
| Internal error or decision fails agent-id consistency check | `503` (if `fail_closed_on_internal_error=True`, the default) |
| Policy `DENY` | `403` |
| Policy `FLAG`, `block_on_flag=True` | `423` |
| Policy `FLAG`, `block_on_flag=False` | Forwarded, decision attached to `request.state` |
| Policy `ALLOW` | Forwarded, decision attached to `request.state` |

An identity-resolution failure never silently becomes `ALLOW`. This was true in
the reference implementation and remains true in the hardened version — it's
now also enforced with explicit, configurable fail-closed flags rather than
being implicit middleware behavior.

**Enabling fail-closed enforcement on a protected route** is not automatic just
because the middleware is installed. You must explicitly set `protected_paths`
(or global `require_agent_id=True`), and decide `block_on_flag` /
`fail_closed_on_registry_error` / `fail_closed_on_internal_error` for your
threat model. See the example in the README.

## Network Configuration

- `RegistryClient` defaults to `network="mainnet"`. Testnet networks (`shasta`,
  `nile`, `testnet`, `devnet`) are **rejected unless you pass
  `allow_testnet=True`** — a production deployment cannot silently end up
  pointed at a testnet registry.
- `rpc_url` must use `https://` unless `allow_insecure_rpc=True` is explicitly
  set, and must not contain embedded credentials.
- Development/testing is done against TRON Shasta with `allow_testnet=True`.

## Reputation and Validation Signals — Known Scale Limitations

The on-chain `ReputationRegistry.getSummary()` encodes feedback as an
arbitrary-precision `(value, valueDecimals)` pair with **no protocol-enforced
range** — a client can leave feedback on a 0–100 scale, a 1–5 scale, or
anything else. `RegistryClient` verifies the decoded value is a finite number;
it does not assume or enforce any particular scale, because doing so would
reject legitimate agents whose feedback simply wasn't given on the scale we
guessed. **Any policy that thresholds on `reputation_average_value` must treat
the scale as deployment-specific and either normalize it or document the
assumption explicitly** — this is not yet resolved in the default reference
policy and is tracked as an open item before the reputation threshold can be
called a real security parameter rather than a placeholder.

`getValidationStatus()`'s response-score semantics (specifically, what index 2
of the returned tuple represents) are implemented against our best reading of
the BofAI SDK, but have not yet been confirmed against a live mainnet contract
call. Treat validation-derived `FLAG`/`ALLOW` decisions as provisional until
this is verified end-to-end against mainnet.

## Supply Chain

- `bankofai.sdk_8004` is installed directly from GitHub
  (`git+https://github.com/BofAI/8004-sdk.git#subdirectory=python`), not from
  PyPI. It is not currently pinned to a specific commit hash in
  `pyproject.toml` — this is a real supply-chain gap (an upstream force-push or
  compromise would be pulled in silently) and should be pinned before a
  production release.
- `tronpy` and `starlette` are the other direct runtime dependencies; no
  automated dependency scanning (`pip-audit` / Dependabot) is configured yet.

## Threat Model

### Addressed
- Unknown or unregistered agent identities reaching a protected endpoint
- Malformed, duplicate, or spoofable identity headers
- Registry/RPC failures being misread as "agent doesn't exist" or silently
  treated as trusted
- Cached identity data leaking mutable state between callers

### Not addressed by this project alone
- Compromise of an agent's private key or of the protected application itself
- Sybil attacks against the underlying TRC-8004 reputation/validation registries
- Malicious behavior by an agent *after* it receives an `ALLOW` decision
- Application-level authorization (this is identity, not permissions) —
  cryptographically binding `X-Agent-Id` to the actual caller/payer requires
  the application to supply an `identity_binding` callback; the middleware
  cannot infer this from a generic HTTP request on its own

These require additional controls: content/action-level policy (e.g. a
second-stage audit layer), rate limiting, transaction limits, or human review
for high-risk operations.

## Security Disclosure Principles

1. Fail safely — an unresolvable identity is never treated as a trusted one.
2. Document real limitations (see above) instead of implying guarantees we
   haven't verified.
3. Separate identity verification from action-level authorization; this
   project intentionally does only the former.
4. Prefer a reproducible test over an unstated assumption — the reputation
   scale issue above was found and fixed this way, not by inspection alone.

## Scope

This policy covers the `x402-identity-guard` reference middleware and policy
layer. It does not extend to applications that integrate it incorrectly, skip
explicit enforcement configuration, or deploy without the additional controls
described above.
