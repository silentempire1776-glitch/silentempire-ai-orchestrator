from typing import Optional, Dict, Any
import datetime
import json

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import ChainRun, ChainStep

CHAIN_ORDER = ["research", "revenue", "sales", "growth", "product", "legal", "systems"]


class ChainStartPayload(BaseModel):
    target: str
    product: str


class ChainEventPayload(BaseModel):
    event: str  # step_started|step_completed|step_failed|chain_started|chain_completed|chain_failed
    agent: Optional[str] = None
    output: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def register_chain_routes(app, SessionLocal, redis_client, log_event):
    """
    Registers Option-B Chain endpoints on the existing FastAPI app.

    Requires:
      - SessionLocal (SQLAlchemy session factory)
      - redis_client (Redis client)
      - log_event (logger)
    """

    @app.post("/chains/start")
    def chains_start(payload: ChainStartPayload):
        db: Session = SessionLocal()
        try:
            chain = ChainRun(
                status="queued",
                target=payload.target,
                product=payload.product,
            )
            db.add(chain)
            db.commit()
            db.refresh(chain)

            # Pre-create steps for progress visibility
            for agent in CHAIN_ORDER:
                db.add(ChainStep(chain_id=chain.id, agent=agent, status="queued"))
            db.commit()

            # Enqueue to ai-firm orchestrator queue (redis keys used by ai-firm)
            envelope = {
                "chain_id": str(chain.id),
                "target": payload.target,
                "product": payload.product,
            }
            redis_client.rpush("queue.orchestrator", json.dumps(envelope))

            log_event(f"[chains] chain {chain.id} queued")

            return {"status": "queued", "chain_id": str(chain.id)}

        finally:
            db.close()

    @app.get("/chains/{chain_id}")
    def chains_get(chain_id: str):
        db: Session = SessionLocal()
        try:
            chain = db.query(ChainRun).filter(ChainRun.id == chain_id).first()
            if not chain:
                raise HTTPException(status_code=404, detail="Chain not found")

            steps = (
                db.query(ChainStep)
                .filter(ChainStep.chain_id == chain_id)
                .all()
            )

            steps_out = [
                {
                    "agent": s.agent,
                    "status": s.status,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                    "error": s.error_message,
                }
                for s in steps
            ]

            return {
                "chain_id": str(chain.id),
                "status": chain.status,
                "target": chain.target,
                "product": chain.product,
                "started_at": chain.started_at,
                "completed_at": chain.completed_at,
                "error": chain.error_message,
                "steps": steps_out,
                "results_by_agent": chain.results_by_agent or {},
                "ceo_summary": chain.ceo_summary,
                "updated_at": chain.updated_at,
            }

        finally:
            db.close()

    @app.post("/chains/{chain_id}/event")
    def chains_event(chain_id: str, payload: ChainEventPayload):
        db: Session = SessionLocal()
        try:
            chain = db.query(ChainRun).filter(ChainRun.id == chain_id).first()
            if not chain:
                raise HTTPException(status_code=404, detail="Chain not found")

            now = datetime.datetime.utcnow()

            # ---- chain-level events ----
            if payload.event == "chain_started":
                chain.status = "running"
                chain.started_at = now

            elif payload.event == "chain_failed":
                chain.status = "failed"
                chain.error_message = payload.error or "unknown chain failure"
                chain.completed_at = now

            elif payload.event == "chain_completed":
                chain.status = "completed"
                chain.completed_at = now

                if payload.meta and isinstance(payload.meta, dict):
                    if "results_by_agent" in payload.meta:
                        chain.results_by_agent = payload.meta.get("results_by_agent")
                    if "ceo_summary" in payload.meta:
                        chain.ceo_summary = payload.meta.get("ceo_summary")

            # ---- step-level events ----
            if payload.agent:
                step = (
                    db.query(ChainStep)
                    .filter(
                        ChainStep.chain_id == chain_id,
                        ChainStep.agent == payload.agent,
                    )
                    .first()
                )

                if step:
                    if payload.event == "step_started":
                        step.status = "running"
                        step.started_at = now

                    elif payload.event == "step_completed":
                        step.status = "completed"
                        step.completed_at = now
                        step.output = payload.output
                        step.meta = payload.meta

                    elif payload.event == "step_failed":
                        step.status = "failed"
                        step.completed_at = now
                        step.error_message = payload.error or "unknown step failure"

            db.commit()
            return {"status": "ok"}

        finally:
            db.close()
