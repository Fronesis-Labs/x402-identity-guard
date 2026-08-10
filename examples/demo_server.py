"""Live x402 Identity Guard demo.

Run:
    python examples/demo_server.py

Then, in another terminal:
    curl -i -H "X-Agent-Id: 1:36" http://127.0.0.1:8000/paid-action
"""

from fastapi import FastAPI, Request

from x402_identity_guard.middleware import IdentityGuardMiddleware


app = FastAPI()

# For this demo we deliberately BLOCK FLAGged agents.
# In production this would be a policy decision.
app.add_middleware(
    IdentityGuardMiddleware,
    block_on_flag=True,
)


@app.post("/paid-action")
async def paid_action(request: Request):
    print()
    print("🔥 PAID ACTION EXECUTED")
    print("   The protected operation was actually reached.")
    print()

    return {
        "status": "executed",
        "message": "The protected operation was allowed.",
    }


@app.get("/")
async def root():
    return {"status": "x402-identity-guard demo running"}


if __name__ == "__main__":
    import uvicorn

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║       x402 IDENTITY GUARD — LIVE DEMO            ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print("Protected endpoint:")
    print("  POST http://127.0.0.1:8000/paid-action")
    print()
    print("Try:")
    print('  curl -i -X POST -H "X-Agent-Id: 1:36" \\')
    print("    http://127.0.0.1:8000/paid-action")
    print()

    uvicorn.run(app, host="127.0.0.1", port=8000)
