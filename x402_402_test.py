import requests

URL = "https://mcp.fronesislabs.com/mcp"

# 1. Initialize MCP session
init_response = requests.post(
    URL,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    },
    json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "x402-local-test",
                "version": "1.0.0",
            },
        },
    },
)

print("=== INITIALIZE ===")
print("HTTP:", init_response.status_code)

session_id = init_response.headers.get("mcp-session-id")

if not session_id:
    raise RuntimeError("MCP session ID was not returned")

print("Session:", session_id)

# 2. Send initialized notification
requests.post(
    URL,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": session_id,
    },
    json={
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    },
)

# 3. Call the paid DCL tool
response = requests.post(
    URL,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": session_id,
    },
    json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "dcl_evaluate_strict",
            "arguments": {
                "response": "This is a harmless x402 payment test.",
                "agent_id": "x402-local-test",
            },
        },
    },
)

print("\n=== TOOL CALL ===")
print("HTTP status:", response.status_code)

print("\nHeaders:")
for key, value in response.headers.items():
    if key.lower() in (
        "x-payment-required",
        "www-authenticate",
        "content-type",
        "mcp-session-id",
    ):
        print(f"  {key}: {value}")

print("\nBody:")
print(response.text)