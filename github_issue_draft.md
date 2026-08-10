## Summary

`AgentRegistry.__init__` defaults `api_url` to `http://localhost:8000`.
This breaks every API-backed method — `get_agent()`, `verify_agent_exists()`,
`search_agents()` — for anyone constructing `AgentRegistry` the way the
docs themselves show, since none of the documented examples pass `api_url`
explicitly.

The real base URL is documented separately on
[`/docs/api`](https://m2mregistry.io/docs/api) ("Base URL:
`https://m2mregistry.io/api`"), but it isn't wired into the SDK's default —
so following the SDK docs and the API docs independently gives two
different, disconnected pieces of information, and only combining them
by hand gets you a working client.

## Steps to reproduce

```python
from trc8004_m2m import AgentRegistry

registry = AgentRegistry(network="shasta")
agents = await registry.search_agents(query="")
```

```
NetworkError: [NETWORK_ERROR] Search failed: All connection attempts failed
```

Confirmed the cause directly:

```python
>>> registry.api.base_url
'http://localhost:8000'
```

## Second, separate issue: /api/* appears unreachable even with the right base URL

After overriding `api_url="https://m2mregistry.io/api"` explicitly,
`search_agents()` still fails — now with a bare timeout instead of a
connection-refused error. Isolated with curl (2026-08-09, ~12:46 UTC):

```
$ curl -v https://m2mregistry.io/health
< HTTP/1.1 404 Not Found
< Server: Vercel
(fast response)

$ curl -v https://m2mregistry.io/api/agents
* Request completely sent off
* Operation timed out after 10009 milliseconds with 0 bytes received
```

The main site (Vercel-hosted frontend) responds normally and quickly.
`/api/*` accepts the TCP/TLS connection but returns zero bytes and hangs
until timeout — no 502/503, just silence. This looks like either a
missing/broken proxy rule from the Vercel frontend to the backend API
service, or the backend service itself being unreachable.

## Expected

`AgentRegistry(network="shasta")` should work out of the box for read
calls, without the caller needing to separately discover and pass
`api_url="https://m2mregistry.io/api"`.

## Suggested fix

Change the default in `AgentRegistry.__init__` from
`http://localhost:8000` to the real per-network base URL (or raise a
clear error telling the caller to pass one, rather than silently trying
localhost). Environment:

- `trc8004-m2m` (latest on PyPI as of 2026-08-09)
- Python 3.12
- Reproduced on Shasta testnet; likely affects mainnet the same way
