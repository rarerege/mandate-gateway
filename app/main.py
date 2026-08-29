"""FastAPI surface for Mandate Gateway.

    uvicorn app.main:app --reload

Endpoints are intentionally thin — all real logic lives in
app/decision/pipeline.py so it can be tested and reused without spinning up
an HTTP server (see tests/test_pipeline.py).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.audit.log import get_entry, verify_chain_integrity
from app.db import init_db
from app.decision.pipeline import MandateGatewayPipeline
from app.schemas import GatewayDecision, OutcomeReport, SourceProtocol

app = FastAPI(
    title="Mandate Gateway",
    description=(
        "Merchant-side authorization and policy layer for agent-initiated "
        "checkouts (AP2 / ACP / UPI-agentic). Verifies the mandate, scores "
        "the agent, applies merchant policy, and returns an explainable "
        "approve / step-up / reject decision with a full audit trail."
    ),
    version="0.1.0",
)

_pipeline: MandateGatewayPipeline | None = None


@app.on_event("startup")
def _startup() -> None:
    init_db()
    global _pipeline
    from scripts.seed_demo import ensure_seeded  # local import: avoids circularity at module load

    ensure_seeded()
    _pipeline = MandateGatewayPipeline()


class AuthorizeRequest(BaseModel):
    protocol: SourceProtocol
    payload: dict


@app.post("/orders/authorize", response_model=GatewayDecision)
def authorize_order(request: AuthorizeRequest) -> GatewayDecision:
    assert _pipeline is not None
    try:
        return _pipeline.authorize(request.payload, request.protocol)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Malformed mandate payload: {exc}") from exc


@app.get("/audit/{decision_id}")
def get_audit_entry(decision_id: str) -> dict:
    entry = get_entry(decision_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No decision with that id")
    return entry


@app.get("/audit-chain/verify")
def audit_chain_verify() -> dict:
    ok, message = verify_chain_integrity()
    return {"intact": ok, "message": message}


@app.post("/outcomes")
def record_outcome(report: OutcomeReport) -> dict:
    entry = get_entry(report.decision_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No decision with that id")
    assert _pipeline is not None
    _pipeline.record_outcome(entry["payload"]["agent_id"], report.was_legitimate)
    return {"status": "recorded"}


@app.get("/policy")
def get_policy() -> dict:
    assert _pipeline is not None
    return _pipeline.policy_engine.policy


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
