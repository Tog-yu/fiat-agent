"""fiat-agent FastAPI entry point (phase A1 skeleton + phase B7 routes).

Minimal app exposing a health endpoint plus user/permission routes (B7).
FastAPI is imported here only; the CLI entry point does not depend on it, so
`python -m apps.cli.main --help` works without FastAPI installed.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes import auth, rag, users

app = FastAPI(title="fiat-agent", version="0.1.0")

app.include_router(users.router)
app.include_router(auth.router)
app.include_router(rag.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "fiat-agent"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
