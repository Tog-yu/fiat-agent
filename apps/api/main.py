"""fiat-agent FastAPI entry point (phase A1 skeleton).

Minimal app exposing a health endpoint. Phase B7 / I1 will add users, auth and
agent routes. FastAPI is imported here only; the CLI entry point does not depend
on it, so `python -m apps.cli.main --help` works without FastAPI installed.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="fiat-agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "fiat-agent"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
