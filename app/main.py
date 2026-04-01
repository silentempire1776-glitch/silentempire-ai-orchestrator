from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
import redis
import datetime
import asyncio
import os

from database import engine, SessionLocal
from models import Base, Job
from chain_bridge import launch_chain


# --------------------------------------------------
# APP INIT
# --------------------------------------------------

app = FastAPI()

# --------------------------------------------------
# LOG STREAM BUFFER + WS CLIENTS
# --------------------------------------------------

loop = None
log_buffer = []
connected_clients: list[WebSocket] = []

def log_event(message: str):
    print(message)
    log_buffer.append(message)

    global loop
    if loop is None:
        return

    for client in list(connected_clients):
        try:
            asyncio.run_coroutine_threadsafe(client.send_text(message), loop)
        except Exception:
            pass

@app.on_event("startup")
async def startup_event():
    global loop
    loop = asyncio.get_running_loop()

# --------------------------------------------------
# DB INIT (table creation)
# --------------------------------------------------

print("CREATING DATABASE TABLES...")
Base.metadata.create_all(bind=engine)
print("DATABASE TABLE CHECK COMPLETE.")

# Create mcp_llm_calls table for comprehensive token tracking
try:
    from sqlalchemy import text as _text
    with engine.begin() as _conn:
        _conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS mcp_llm_calls (
                id BIGSERIAL PRIMARY KEY,
                agent TEXT,
                model TEXT,
                provider TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                tokens_total INTEGER DEFAULT 0,
                cost_usd DOUBLE PRECISION DEFAULT 0.0,
                chain_id TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        _conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_mcp_llm_calls_agent ON mcp_llm_calls(agent)"))
        _conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_mcp_llm_calls_created ON mcp_llm_calls(created_at)"))
    print("mcp_llm_calls table ready")

except Exception as _e:
    print("mcp_llm_calls table error:", _e)

# Per-model health tracking table
try:
    from sqlalchemy import text as _text2
    with engine.begin() as _conn2:
        _conn2.execute(_text2("""
            CREATE TABLE IF NOT EXISTS model_health (
                model TEXT PRIMARY KEY,
                provider TEXT DEFAULT 'nvidia',
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                health_score DOUBLE PRECISION DEFAULT 1.0,
                avg_latency_ms DOUBLE PRECISION DEFAULT 0.0,
                total_latency_ms DOUBLE PRECISION DEFAULT 0.0,
                last_used TIMESTAMP DEFAULT NOW(),
                last_success TIMESTAMP,
                last_failure TIMESTAMP
            )
        """))
    print("model_health table ready")
except Exception as _e2:
    print("model_health table error:", _e2)

try:
    from sqlalchemy import text as _text3
    with engine.begin() as _c3:
        _c3.execute(_text3("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                name TEXT,
                messages TEXT,
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
    print("chat_sessions table ready")
except Exception as _e3:
    print("chat_sessions table error:", _e3)
except Exception as _e:
    print("model_health table error:", _e)

# --------------------------------------------------
# REDIS
# --------------------------------------------------

redis_client = redis.Redis(host="redis", port=6379, decode_responses=True)

# --------------------------------------------------
# MODELS
# --------------------------------------------------

class JobRequest(BaseModel):
    type: str
    payload: dict

class ChainRequest(BaseModel):
    target: str
    product: str

class RunPayload(BaseModel):
    task: str
    agent: str | None = None

class FilePayload(BaseModel):
    content: str = ""

class ChainEventPayload(BaseModel):
    agent: str | None = None
    output: str | None = None
    data: dict | None = None

# --------------------------------------------------
# HEALTH
# --------------------------------------------------


@app.post("/agent/model-override")
async def set_agent_model_override(request: Request):
    """Set the active model for Jarvis via Redis. Takes effect immediately."""
    try:
        body = await request.json()
        agent = body.get("agent", "jarvis")
        model = body.get("model", "").strip()

        if not model:
            raise HTTPException(status_code=400, detail="model is required")

        import redis as _redis_mod
        _r = _redis_mod.from_url(
            os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
            decode_responses=True
        )

        if agent == "jarvis":
            if not model:
                _r.delete("jarvis:model_override")
                return {"status": "ok", "agent": agent, "model": "", "message": "Jarvis override cleared"}
            _r.set("jarvis:model_override", model)
            return {"status": "ok", "agent": agent, "model": model,
                    "message": f"Jarvis will now use {model} on next message"}
        else:
            if not model:
                _r.delete(f"agent:model_override:{agent}")
                return {"status": "ok", "agent": agent, "model": "", "message": f"{agent} override cleared"}
            _r.set(f"agent:model_override:{agent}", model)
            return {"status": "ok", "agent": agent, "model": model}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agent/model-override")
async def get_agent_model_override():
    """Get current model overrides for all agents."""
    ALL_AGENT_DEFAULTS = {
        "jarvis":   os.getenv("MODEL_JARVIS_ORCHESTRATOR", "moonshotai/kimi-k2.5"),
        "research": os.getenv("MODEL_RESEARCH",            "moonshotai/kimi-k2-thinking"),
        "revenue":  os.getenv("MODEL_FINANCIAL_STRATEGY",  "moonshotai/kimi-k2.5"),
        "sales":    os.getenv("MODEL_MARKETING",           "moonshotai/kimi-k2.5"),
        "growth":   os.getenv("MODEL_STRATEGIC_PLANNING",  "moonshotai/kimi-k2.5"),
        "product":  os.getenv("MODEL_CODING",              "moonshotai/kimi-k2-instruct"),
        "legal":    os.getenv("MODEL_LEGAL_STRUCTURING",   "moonshotai/kimi-k2-thinking"),
        "systems":  os.getenv("MODEL_SYSTEMS",             "qwen/qwen3-coder-480b-a35b-instruct"),
        "code":     os.getenv("MODEL_MICRO_CODING",        "qwen/qwen3-coder-480b-a35b-instruct"),
        "voice":    os.getenv("MODEL_FAST_WORKER",         "meta/llama-4-maverick-17b-128e-instruct"),
    }
    try:
        import redis as _redis_mod
        _r = _redis_mod.from_url(
            os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
            decode_responses=True
        )
        result = {}
        for agent, default in ALL_AGENT_DEFAULTS.items():
            # Check jarvis-specific key first for backwards compat
            if agent == "jarvis":
                override = _r.get("jarvis:model_override")
            else:
                override = _r.get(f"agent:model_override:{agent}")
            result[agent] = override if override and override.strip() else default
        return result
    except Exception as e:
        return {**ALL_AGENT_DEFAULTS, "error": str(e)}


@app.get("/health")
def health():
    return {"status": "ok"}

# --------------------------------------------------
# DEAD LETTER QUEUE
# --------------------------------------------------

@app.get("/admin/dead")
def view_dead_queue():
    dead_jobs = redis_client.lrange("queue:dead", 0, -1)
    return {"dead_count": len(dead_jobs), "job_ids": dead_jobs}

@app.post("/admin/retry/{job_id}")
def retry_dead_job(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != "failed":
            raise HTTPException(status_code=400, detail="Job is not failed")

        job.status = "pending"
        job.retry_count = 0
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        db.commit()

        redis_client.lrem("queue:dead", 0, job_id)
        redis_client.rpush("queue:default", job_id)

        return {"message": f"Job {job_id} requeued successfully"}
    finally:
        db.close()

# --------------------------------------------------
# JOB CRUD
# --------------------------------------------------

@app.post("/jobs")
def create_job(request: JobRequest):
    db = SessionLocal()
    try:
        job = Job(type=request.type, payload=request.payload, status="pending")
        db.add(job)
        db.commit()
        db.refresh(job)

        redis_client.rpush("queue:default", str(job.id))
        return {"job_id": str(job.id)}
    finally:
        db.close()

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "id": str(job.id),
            "status": job.status,
            "payload": job.payload,
            "result": job.result,
        }
    finally:
        db.close()

# --------------------------------------------------
# METRICS
# --------------------------------------------------

@app.get("/metrics")
def get_metrics():
    db = SessionLocal()
    try:
        total_jobs = db.query(Job).count()
        pending_jobs = db.query(Job).filter(Job.status == "pending").count()
        running_jobs = db.query(Job).filter(Job.status == "running").count()
        completed_jobs = db.query(Job).filter(Job.status == "completed").count()
        failed_jobs = db.query(Job).filter(Job.status == "failed").count()

        dead_queue_size = redis_client.llen("queue:dead")
        active_queue_size = redis_client.llen("queue:default")

        return {
            "total_jobs": total_jobs,
            "pending_jobs": pending_jobs,
            "running_jobs": running_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "active_queue_size": active_queue_size,
            "dead_queue_size": dead_queue_size,
        }
    finally:
        db.close()

@app.get("/metrics/usage")
def get_usage_metrics():
    db = SessionLocal()
    try:
        total_tokens_input = db.query(func.coalesce(func.sum(Job.tokens_input), 0)).scalar()
        total_tokens_output = db.query(func.coalesce(func.sum(Job.tokens_output), 0)).scalar()
        total_cost = db.query(func.coalesce(func.sum(Job.estimated_cost_usd), 0.0)).scalar()

        provider_rows = db.query(
            Job.provider,
            func.coalesce(func.sum(Job.estimated_cost_usd), 0.0)
        ).group_by(Job.provider).all()

        provider_breakdown = {row[0]: float(row[1]) for row in provider_rows if row[0]}

        model_rows = db.query(
            Job.model_used,
            func.coalesce(func.sum(Job.estimated_cost_usd), 0.0)
        ).group_by(Job.model_used).all()

        model_breakdown = {row[0]: float(row[1]) for row in model_rows if row[0]}

        since = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        last_24h_cost = db.query(
            func.coalesce(func.sum(Job.estimated_cost_usd), 0.0)
        ).filter(Job.completed_at >= since).scalar()

        return {
            "all_time": {
                "tokens_input": int(total_tokens_input or 0),
                "tokens_output": int(total_tokens_output or 0),
                "total_cost_usd": float(total_cost or 0.0),
            },
            "last_24_hours": {"cost_usd": float(last_24h_cost or 0.0)},
            "by_provider": provider_breakdown,
            "by_model": model_breakdown,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()

# --------------------------------------------------
# CHAIN LAUNCH
# --------------------------------------------------

@app.post("/launch-chain")
def launch_chain_endpoint(req: ChainRequest):
    from shared.redis_bus import enqueue
    launch_chain(req.target, req.product)
    return {"status": "chain_started"}

#    enqueue("queue.orchestrator", {
#         "task_type": "start_chain",
#         "payload": {
#             "target": request.target,
#             "product": request.product
#         }
#     })

# --------------------------------------------------
# STORE  CHAT EVENTS ENSPOINT
# --------------------------------------------------
from fastapi import Request
import json

@app.post("/chains/{chain_id}/event")
async def chain_event(chain_id: str, request: Request):

    try:
        payload = await request.json()
    except Exception:
        return {"status": "invalid_json"}

    try:
        from database import engine
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO chain_events (chain_id, event, agent, output, data)
                VALUES (:chain_id, :event, :agent, :output, :data)
            """), {
                "chain_id": chain_id,
                "event": payload.get("event"),
                "agent": payload.get("agent"),
                "output": payload.get("output"),
                "data": json.dumps(payload)
            })

    except Exception as e:
        print("CHAIN EVENT ERROR:", e)
        return {"status": "error"}

    return {"status": "ok"}

# --------------------------------------------------
# ADD CHAT HISTORY ENSPOINT
# --------------------------------------------------
from sqlalchemy import text
from database import engine

@app.get("/chains/{chain_id}")
def get_chain(chain_id: str):

    try:
        with engine.begin() as conn:

            rows = conn.execute(text("""
                SELECT agent, output, data, created_at
                FROM chain_events
                WHERE chain_id = :chain_id
                ORDER BY created_at ASC
            """), {"chain_id": chain_id}).fetchall()

        events = []

        for r in rows:
            events.append({
                "agent": r[0],
                "output": r[1],
                "data": r[2],
                "timestamp": str(r[3])
            })

        return {"events": events}

    except Exception as e:
        print("GET CHAIN ERROR:", e)
        return {"events": []}

# --------------------------------------------------
# FILE BROWSER (single app, no re-init)
# --------------------------------------------------

BASE_PATH = "/srv/silentempire"

@app.get("/files")
def list_files(path: str = ""):
    clean_path = path.lstrip("/")
    full_path = os.path.abspath(os.path.join(BASE_PATH, clean_path))

    if not full_path.startswith(BASE_PATH):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Not Found")

    if os.path.isdir(full_path):
        files = [
            {"name": name, "isDirectory": os.path.isdir(os.path.join(full_path, name))}
            for name in sorted(os.listdir(full_path))
        ]
        return {"files": files}

    with open(full_path, "r") as f:
        content = f.read()
    return {"content": content}

@app.post("/file")
def save_file(path: str, payload: FilePayload):
    clean_path = path.lstrip("/")
    full_path = os.path.abspath(os.path.join(BASE_PATH, clean_path))

    if not full_path.startswith(BASE_PATH):
        raise HTTPException(status_code=403, detail="Access denied")

    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(payload.content)

    return {"status": "saved"}

@app.delete("/file")
def delete_file(path: str):
    clean_path = path.lstrip("/")
    full_path = os.path.abspath(os.path.join(BASE_PATH, clean_path))

    if not full_path.startswith(BASE_PATH):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    os.remove(full_path)
    return {"status": "deleted"}

@app.post("/create-file")
def create_file(path: str):
    clean_path = path.lstrip("/")
    full_path = os.path.abspath(os.path.join(BASE_PATH, clean_path))

    if not full_path.startswith(BASE_PATH):
        raise HTTPException(status_code=403, detail="Access denied")
    if os.path.exists(full_path):
        raise HTTPException(status_code=400, detail="File already exists")

    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write("")

    return {"status": "created"}

# --------------------------------------------------
# RUN TASK (DB-first + UUID-only enqueue)
# --------------------------------------------------

@app.post("/run")
def run_task(payload: RunPayload):
    db: Session = SessionLocal()
    try:
        job = Job(
            type="orchestrator",
            status="queued",
            payload={"task": payload.task, "agent": payload.agent},
        )

        db.add(job)
        db.commit()
        db.refresh(job)

        redis_client.rpush("queue:orchestrator", str(job.id))
        log_event(f"[orchestrator] job {job.id} queued")

        return {"status": "queued", "job_id": str(job.id)}
    finally:
        db.close()


# TEMP DISABLE CHAINS: from chains_api import register_chain_routes
#from services.api.chains_api import register_chain_routes
#register_chain_routes(app, SessionLocal, redis_client, log_event)


# --------------------------------------------------
# WEBSOCKET LOG STREAM
# --------------------------------------------------

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)

# --------------------------------------------------
# CHAT (Jarvis default; chain optional)
# --------------------------------------------------
@app.post("/chat")
def chat_endpoint(req: dict):

    from shared.redis_bus import enqueue
    import uuid

    chain_id = str(uuid.uuid4())

    message = req.get("message") or ""
    mode = (req.get("mode") or "jarvis").strip().lower()  # "jarvis" (default) or "chain"

    # Common envelope fields (orchestrator expects chain_id top-level)
    session_id = req.get("session_id") or ""
    telegram_chat_id = req.get("telegram_chat_id") or ""
    envelope = {
        "chain_id": chain_id,
        "agent": "jarvis",
        "session_id": session_id,
        "telegram_chat_id": telegram_chat_id,
        "payload": {
            "message": message,
            "chain_id": chain_id,
            "session_id": session_id,
            "telegram_chat_id": telegram_chat_id,
        }
    }

    # Default: Jarvis-only interactive response
    if mode == "jarvis":
        envelope["task_type"] = "jarvis_chat"
        envelope["target"] = "chat"
        envelope["product"] = message
        enqueue("queue.orchestrator", envelope)
        return {"chain_id": chain_id, "mode": "jarvis"}

    # sys_command: direct infrastructure execution via systems agent
    if mode == "sys":
        envelope["task_type"] = "sys_command"
        envelope["target"] = "sys_command"
        envelope["product"] = message
        enqueue("queue.orchestrator", envelope)
        return {"chain_id": chain_id, "mode": "sys"}

    # Optional: full executive chain (existing behavior)
    envelope["task_type"] = "chat"
    envelope["target"] = "chat"
    envelope["product"] = message
    enqueue("queue.orchestrator", envelope)
    return {"chain_id": chain_id, "mode": "chain"}

# --------------------------------------------------
# TEMP ENDPOINT FOR CHAT
# --------------------------------------------------
@app.post("/debug/respond/{chain_id}")
def debug_response(chain_id: str):

    from shared.artifact_store import log_chain_event

    log_chain_event(chain_id, {
        "agent": "jarvis",
        "output": "Jarvis online. System responding."
    })

    return {"status": "ok"}


# --------------------------------------------------
# CHAT SESSIONS (cross-device sync)
# --------------------------------------------------

@app.get("/sessions")
def list_sessions():
    from models import Job  # noqa — confirm models loads
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, name, messages, created_at, updated_at
            FROM chat_sessions
            ORDER BY updated_at DESC
        """)).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "message_count": len(r[2] or []),
                "created_at": str(r[3]),
                "updated_at": str(r[4]),
            }
            for r in rows
        ]
    finally:
        db.close()
    db = SessionLocal()
    try:
        sessions = db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "message_count": len(s.messages or []),
                "created_at": str(s.created_at),
                "updated_at": str(s.updated_at),
            }
            for s in sessions
        ]
    finally:
        db.close()


@app.post("/sessions")
def create_session(req: dict):
    import uuid, datetime, json
    from sqlalchemy import text
    db = SessionLocal()
    try:
        sid = str(uuid.uuid4())[:8]
        name = req.get("name", "New Chat")
        now = datetime.datetime.utcnow()
        db.execute(text("""
            INSERT INTO chat_sessions (id, name, messages, created_at, updated_at)
            VALUES (:id, :name, :messages, :created_at, :updated_at)
        """), {"id": sid, "name": name, "messages": json.dumps([]), "created_at": now, "updated_at": now})
        db.commit()
        return {"id": sid, "name": name, "messages": [], "created_at": str(now), "updated_at": str(now)}
    finally:
        db.close()


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    import json as _json
    from sqlalchemy import text
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT id, name, messages, created_at, updated_at FROM chat_sessions WHERE id = :id"), {"id": session_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        msgs = row[2]
        if isinstance(msgs, str):
            msgs = _json.loads(msgs)
        return {"id": row[0], "name": row[1], "messages": msgs or [], "created_at": str(row[3]), "updated_at": str(row[4])}
    finally:
        db.close()


@app.put("/sessions/{session_id}")
async def update_session(session_id: str, request: Request):
    import datetime, json as _json
    from sqlalchemy import text
    body = await request.json()
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        updates = {"id": session_id, "updated_at": now}
        parts = ["updated_at = :updated_at"]
        if "name" in body:
            parts.append("name = :name")
            updates["name"] = body["name"]
        if "messages" in body:
            parts.append("messages = :messages")
            updates["messages"] = _json.dumps(body["messages"])
        db.execute(text(f"UPDATE chat_sessions SET {', '.join(parts)} WHERE id = :id"), updates)
        db.commit()
        msg_count = len(body.get("messages", []))
        return {"id": session_id, "message_count": msg_count, "updated_at": str(now)}
    finally:
        db.close()


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM chat_sessions WHERE id = :id"), {"id": session_id})
        db.commit()
        return {"status": "deleted"}
    finally:
        db.close()

# MCP ROUTES
from mcp_routes import router as mcp_router
app.include_router(mcp_router)

# VOICE ROUTES
from voice_routes import router as voice_router
app.include_router(voice_router)


@app.get("/metrics/agents")
def get_agent_metrics():
    db = SessionLocal()
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta
        since_today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        since_24h   = datetime.utcnow() - timedelta(hours=24)
        since_1h    = datetime.utcnow() - timedelta(hours=1)

        def qry(since):
            try:
                rows = db.execute(text(
                    "SELECT payload->>'agent' AS agent,"
                    " COALESCE(SUM(tokens_input),0),"
                    " COALESCE(SUM(tokens_output),0),"
                    " COALESCE(SUM(tokens_input+tokens_output),0),"
                    " COALESCE(SUM(estimated_cost_usd),0.0)"
                    " FROM jobs WHERE created_at >= :s"
                    " AND payload->>'agent' IS NOT NULL AND payload->>'agent' != ''"
                    " GROUP BY payload->>'agent'"
                ), {"s": since}).fetchall()
                return {r[0]: {"tokens_in": int(r[1] or 0), "tokens_out": int(r[2] or 0), "tokens_total": int(r[3] or 0), "cost": float(r[4] or 0)} for r in rows if r[0]}
            except Exception as e:
                print("agent metrics qry error:", e)
                return {}

        today_map = qry(since_today)
        h24_map   = qry(since_24h)

        try:
            live_rows = db.execute(text(
                "SELECT DISTINCT ON (agent) agent, data->>'event' AS event"
                " FROM chain_events WHERE agent IS NOT NULL AND created_at >= :s"
                " ORDER BY agent, created_at DESC"
            ), {"s": since_1h}).fetchall()
            state_map = {}
            for row in live_rows:
                if row[0]:
                    state_map[row[0]] = "working" if row[1] == "step_started" else "idle"
        except Exception as e:
            print("live state error:", e)
            state_map = {}

        return {"today": today_map, "last_24h": h24_map, "states": state_map}
    except Exception as e:
        return {"error": str(e), "today": {}, "last_24h": {}, "states": {}}
    finally:
        db.close()


@app.get("/metrics/agents/live")
def get_agent_live_states():
    db = SessionLocal()
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta
        since = datetime.utcnow() - timedelta(hours=1)
        rows = db.execute(text(
            "SELECT DISTINCT ON (agent) agent, data->>'event' AS event"
            " FROM chain_events WHERE agent IS NOT NULL AND created_at >= :s"
            " ORDER BY agent, created_at DESC"
        ), {"s": since}).fetchall()
        states = {}
        for row in rows:
            if row[0]:
                states[row[0]] = "working" if row[1] == "step_started" else "idle"
        return {"states": states}
    except Exception as e:
        return {"states": {}, "error": str(e)}
    finally:
        db.close()


@app.get("/metrics/agents")
def get_agent_metrics():
    """Per-agent token usage and live state. Uses correct column names."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta
        now_dt       = datetime.utcnow()
        since_today  = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        since_24h    = now_dt - timedelta(hours=24)
        since_1h     = now_dt - timedelta(hours=1)
        month_start  = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def agent_tokens(since):
            try:
                rows = db.execute(text(
                    "SELECT payload->>'agent' AS agent,"
                    " COALESCE(SUM(tokens_input),0),"
                    " COALESCE(SUM(tokens_output),0),"
                    " COALESCE(SUM(COALESCE(tokens_input,0)+COALESCE(tokens_output,0)),0),"
                    " COALESCE(SUM(estimated_cost_usd),0.0)"
                    " FROM jobs WHERE created_at >= :s"
                    " AND payload->>'agent' IS NOT NULL AND payload->>'agent' != ''"
                    " GROUP BY payload->>'agent'"
                ), {"s": since}).fetchall()
                return {
                    r[0]: {
                        "tokens_in": int(r[1] or 0),
                        "tokens_out": int(r[2] or 0),
                        "tokens_total": int(r[3] or 0),
                        "cost": float(r[4] or 0)
                    }
                    for r in rows if r[0]
                }
            except Exception as e:
                print("[metrics/agents] token query error:", e)
                return {}

        today_map = agent_tokens(since_today)
        h24_map   = agent_tokens(since_24h)

        # Live agent state: uses `event` and `agent` as direct columns (not JSONB)
        try:
            live_rows = db.execute(text(
                "SELECT DISTINCT ON (agent) agent, event, created_at"
                " FROM chain_events"
                " WHERE agent IS NOT NULL AND agent != '' AND created_at >= :s"
                " ORDER BY agent, created_at DESC"
            ), {"s": since_1h}).fetchall()
            state_map = {}
            for row in live_rows:
                ag, ev = row[0], row[1]
                if ag:
                    state_map[ag] = "working" if ev == "step_started" else "idle"
        except Exception as e:
            print("[metrics/agents] state query error:", e)
            state_map = {}

        # Model token usage (today, yesterday, this week)
        try:
            yesterday_start = (now_dt - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_end   = since_today
            week_start      = now_dt - timedelta(days=7)

            def model_tokens(since, until=None):
                cond = "WHERE created_at >= :s"
                params = {"s": since}
                if until:
                    cond += " AND created_at < :u"
                    params["u"] = until
                try:
                    rows = db.execute(text(
                        "SELECT model_used,"
                        " COALESCE(SUM(COALESCE(tokens_input,0)+COALESCE(tokens_output,0)),0) AS tt"
                        " FROM jobs " + cond +
                        " AND model_used IS NOT NULL GROUP BY model_used ORDER BY tt DESC LIMIT 8"
                    ), params).fetchall()
                    return {r[0]: int(r[1] or 0) for r in rows if r[0]}
                except Exception as e:
                    print("[metrics/agents] model token query:", e)
                    return {}

            models_today     = model_tokens(since_today)
            models_yesterday = model_tokens(yesterday_start, yesterday_end)
            models_week      = model_tokens(week_start)
        except Exception as e:
            print("[metrics/agents] model tokens error:", e)
            models_today = models_yesterday = models_week = {}

        # Current month cost
        try:
            month_cost = db.execute(text(
                "SELECT COALESCE(SUM(estimated_cost_usd),0.0) FROM jobs WHERE created_at >= :s"
            ), {"s": month_start}).scalar()
        except Exception as e:
            print("[metrics/agents] month cost error:", e)
            month_cost = 0.0

        return {
            "today":           today_map,
            "last_24h":        h24_map,
            "states":          state_map,
            "models_today":    models_today,
            "models_yesterday":models_yesterday,
            "models_week":     models_week,
            "month_cost":      float(month_cost or 0),
        }
    except Exception as e:
        return {"error": str(e), "today": {}, "last_24h": {}, "states": {}, "models_today": {}, "models_yesterday": {}, "models_week": {}, "month_cost": 0.0}
    finally:
        db.close()


@app.get("/metrics/agents/live")
def get_agent_live_states():
    """Fast live-state poll. Uses correct column names."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta
        since = datetime.utcnow() - timedelta(hours=1)
        rows = db.execute(text(
            "SELECT DISTINCT ON (agent) agent, event"
            " FROM chain_events"
            " WHERE agent IS NOT NULL AND agent != '' AND created_at >= :s"
            " ORDER BY agent, created_at DESC"
        ), {"s": since}).fetchall()
        states = {}
        for row in rows:
            if row[0]:
                states[row[0]] = "working" if row[1] == "step_started" else "idle"
        return {"states": states}
    except Exception as e:
        return {"states": {}, "error": str(e)}
    finally:
        db.close()


@app.get("/metrics/agents")
def get_agent_metrics():
    db = SessionLocal()
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta
        now_dt      = datetime.utcnow()
        since_today = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        since_24h   = now_dt - timedelta(hours=24)
        since_1h    = now_dt - timedelta(hours=1)
        month_start = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        yesterday_s = (now_dt - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_e = since_today
        week_start  = now_dt - timedelta(days=7)

        def safe(fn):
            try: return fn()
            except Exception as e: print("[metrics/agents]", e); return {}

        def model_tokens(since, until=None):
            cond = "WHERE created_at >= :s AND model_used IS NOT NULL AND tokens_input IS NOT NULL"
            params = {"s": since}
            if until:
                cond += " AND created_at < :u"
                params["u"] = until
            rows = db.execute(text(
                "SELECT model_used,"
                " COALESCE(SUM(COALESCE(tokens_input,0)+COALESCE(tokens_output,0)),0) AS tt"
                " FROM jobs " + cond +
                " GROUP BY model_used ORDER BY tt DESC LIMIT 8"
            ), params).fetchall()
            return {r[0]: int(r[1] or 0) for r in rows if r[0]}

        models_today     = safe(lambda: model_tokens(since_today))
        models_yesterday = safe(lambda: model_tokens(yesterday_s, yesterday_e))
        models_week      = safe(lambda: model_tokens(week_start))

        # Per-agent token usage — try payload->>'agent' first, fall back to empty
        def agent_tokens(since):
            try:
                rows = db.execute(text(
                    "SELECT payload->>'agent' AS ag,"
                    " COALESCE(SUM(COALESCE(tokens_input,0)+COALESCE(tokens_output,0)),0) AS tt,"
                    " COALESCE(SUM(estimated_cost_usd),0.0) AS cost"
                    " FROM jobs WHERE created_at >= :s"
                    " AND payload->>'agent' IS NOT NULL AND payload->>'agent' != ''"
                    " AND (tokens_input IS NOT NULL OR tokens_output IS NOT NULL)"
                    " GROUP BY payload->>'agent'"
                ), {"s": since}).fetchall()
                return {r[0]: {"tokens_total": int(r[1] or 0), "cost": float(r[2] or 0)} for r in rows if r[0]}
            except Exception as e:
                print("[agent_tokens]", e)
                return {}

        today_map = agent_tokens(since_today)
        h24_map   = agent_tokens(since_24h)

        # Live agent state — uses direct column names (not JSONB)
        try:
            live_rows = db.execute(text(
                "SELECT DISTINCT ON (agent) agent, event"
                " FROM chain_events"
                " WHERE agent IS NOT NULL AND agent != ''"
                " AND created_at >= :s"
                " ORDER BY agent, created_at DESC"
            ), {"s": since_1h}).fetchall()
            state_map = {r[0]: ("working" if r[1] == "step_started" else "idle") for r in live_rows if r[0]}
        except Exception as e:
            print("[live_state]", e)
            state_map = {}

        # Month cost
        month_cost = 0.0
        try:
            month_cost = float(db.execute(text(
                "SELECT COALESCE(SUM(estimated_cost_usd),0.0) FROM jobs WHERE created_at >= :s"
            ), {"s": month_start}).scalar() or 0)
        except Exception as e:
            print("[month_cost]", e)

        # All-time token totals
        all_tokens_in  = 0
        all_tokens_out = 0
        try:
            r = db.execute(text(
                "SELECT COALESCE(SUM(tokens_input),0), COALESCE(SUM(tokens_output),0) FROM jobs"
            )).fetchone()
            all_tokens_in  = int(r[0] or 0)
            all_tokens_out = int(r[1] or 0)
        except Exception as e:
            print("[all_tokens]", e)

        return {
            "today":            today_map,
            "last_24h":         h24_map,
            "states":           state_map,
            "models_today":     models_today,
            "models_yesterday": models_yesterday,
            "models_week":      models_week,
            "month_cost":       month_cost,
            "all_tokens_in":    all_tokens_in,
            "all_tokens_out":   all_tokens_out,
        }
    except Exception as e:
        return {"error": str(e), "today": {}, "last_24h": {}, "states": {},
                "models_today": {}, "models_yesterday": {}, "models_week": {},
                "month_cost": 0.0, "all_tokens_in": 0, "all_tokens_out": 0}
    finally:
        db.close()


@app.get("/metrics/agents/live")
def get_agent_live_states():
    db = SessionLocal()
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta
        # Check last 10 minutes - catch fast chains
        since = datetime.utcnow() - timedelta(minutes=10)
        rows = db.execute(text(
            "SELECT DISTINCT ON (agent) agent, event, created_at"
            " FROM chain_events"
            " WHERE agent IS NOT NULL AND agent != ''"
            " AND created_at >= :s"
            " ORDER BY agent, created_at DESC"
        ), {"s": since}).fetchall()
        from datetime import timezone
        now_dt = datetime.utcnow()
        states = {}
        for r in rows:
            if not r[0]: continue
            ev = r[1]
            # If step_started and less than 3 minutes ago with no completion = working
            age = (now_dt - r[2]).total_seconds()
            if ev == "step_started" and age < 180:
                states[r[0]] = "working"
            elif ev in ("step_completed", "step_failed"):
                states[r[0]] = "idle"
            else:
                states[r[0]] = "idle"
        return {"states": states}
    except Exception as e:
        return {"states": {}, "error": str(e)}
    finally:
        db.close()


@app.post("/metrics/llm/record")
async def record_llm_call(request: Request):
    """Called by MCP llm_router after each LLM call to record usage."""
    try:
        body = await request.json()
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO mcp_llm_calls (agent, model, provider, tokens_in, tokens_out, tokens_total, cost_usd, chain_id)
                VALUES (:agent, :model, :provider, :tin, :tout, :ttotal, :cost, :chain_id)
            """), {
                "agent":    body.get("agent", "unknown"),
                "model":    body.get("model", ""),
                "provider": body.get("provider", ""),
                "tin":      body.get("tokens_in", 0),
                "tout":     body.get("tokens_out", 0),
                "ttotal":   body.get("tokens_total", 0),
                "cost":     body.get("cost_usd", 0.0),
                "chain_id": body.get("chain_id", ""),
            })
        return {"status": "recorded"}
    except Exception as e:
        print("[metrics/llm/record] error:", e)
        return {"status": "error", "detail": str(e)}


@app.get("/metrics/llm")
def get_llm_metrics():
    from sqlalchemy import text
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        now    = datetime.utcnow()
        today  = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week   = now - timedelta(days=7)
        yest_s = (now-timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        yest_e = today
        month  = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)

        def qry(since, until=None, grp="agent"):
            cond = "WHERE created_at >= :s AND "+grp+" IS NOT NULL"
            p = {"s": since}
            if until:
                cond += " AND created_at < :u"
                p["u"] = until
            try:
                rows = db.execute(text(
                    "SELECT "+grp+","
                    " COALESCE(SUM(tokens_total),0),"
                    " COALESCE(SUM(tokens_in),0),"
                    " COALESCE(SUM(tokens_out),0),"
                    " COALESCE(SUM(cost_usd),0.0)"
                    " FROM mcp_llm_calls "+cond+" GROUP BY "+grp+" ORDER BY 2 DESC"
                ), p).fetchall()
                return {r[0]:{"tokens_total":int(r[1]or 0),"tokens_in":int(r[2]or 0),"tokens_out":int(r[3]or 0),"cost":float(r[4]or 0)} for r in rows if r[0]}
            except Exception as e:
                print("[metrics/llm]",e)
                return {}

        mc = float(db.execute(text("SELECT COALESCE(SUM(cost_usd),0) FROM mcp_llm_calls WHERE created_at>=:s"),{"s":month}).scalar() or 0)
        rt = int(db.execute(text("SELECT COUNT(*) FROM mcp_llm_calls WHERE created_at>=:s"),{"s":today}).scalar() or 0)

        return {
            "by_agent_today":     qry(today),
            "by_agent_week":      qry(week),
            "by_model_today":     qry(today,  grp="model"),
            "by_model_yesterday": qry(yest_s, yest_e, grp="model"),
            "by_model_week":      qry(week,   grp="model"),
            "month_cost":         mc,
            "total_requests_today": rt,
        }
    except Exception as e:
        return {"error":str(e)}
    finally:
        db.close()



@app.get("/metrics/model_health")
def get_model_health():
    """Per-model health scores, latency, and usage stats."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Get model health from model_health table
        rows = db.execute(text(
            "SELECT model, provider, health_score, avg_latency_ms,"
            " success_count, failure_count, last_used, last_success, last_failure"
            " FROM model_health ORDER BY last_used DESC"
        )).fetchall()

        health = {}
        for r in rows:
            health[r[0]] = {
                "model":         r[0],
                "provider":      r[1] or "nvidia",
                "health_score":  round(float(r[2] or 1.0), 3),
                "avg_latency_ms": int(r[3] or 0),
                "success_count": int(r[4] or 0),
                "failure_count": int(r[5] or 0),
                "last_used":     r[6].isoformat() if r[6] else None,
            }

        # Also include any models from mcp_llm_calls not yet in model_health
        try:
            llm_rows = db.execute(text(
                "SELECT DISTINCT model FROM mcp_llm_calls WHERE model IS NOT NULL"
            )).fetchall()
            for r in llm_rows:
                if r[0] and r[0] not in health:
                    health[r[0]] = {
                        "model": r[0], "provider": "nvidia",
                        "health_score": 1.0, "avg_latency_ms": 0,
                        "success_count": 0, "failure_count": 0, "last_used": None,
                    }
        except Exception:
            pass

        return {"models": health, "count": len(health)}
    except Exception as e:
        return {"models": {}, "count": 0, "error": str(e)}
    finally:
        db.close()


@app.post("/metrics/model_health/update")
async def update_model_health(request: Request):
    """Called by worker after each job to update per-model health score."""
    try:
        body = await request.json()
        model    = body.get("model", "")
        provider = body.get("provider", "nvidia")
        success  = body.get("success", True)
        latency  = body.get("latency_ms", 0)
        if not model:
            return {"status": "skipped"}
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO model_health (model, provider, success_count, failure_count,
                    health_score, avg_latency_ms, total_latency_ms, last_used,
                    last_success, last_failure)
                VALUES (:model, :provider,
                    CASE WHEN :success THEN 1 ELSE 0 END,
                    CASE WHEN :success THEN 0 ELSE 1 END,
                    CASE WHEN :success THEN 1.0 ELSE 0.0 END,
                    :latency, :latency,
                    NOW(),
                    CASE WHEN :success THEN NOW() ELSE NULL END,
                    CASE WHEN :success THEN NULL ELSE NOW() END
                )
                ON CONFLICT (model) DO UPDATE SET
                    success_count = model_health.success_count + CASE WHEN :success THEN 1 ELSE 0 END,
                    failure_count = model_health.failure_count + CASE WHEN :success THEN 0 ELSE 1 END,
                    health_score  = (model_health.success_count + CASE WHEN :success THEN 1 ELSE 0 END)::float
                                  / NULLIF(model_health.success_count + model_health.failure_count + 1, 0),
                    total_latency_ms = model_health.total_latency_ms + :latency,
                    avg_latency_ms   = (model_health.total_latency_ms + :latency)
                                     / NULLIF(model_health.success_count + model_health.failure_count + 1, 0),
                    last_used    = NOW(),
                    last_success = CASE WHEN :success THEN NOW() ELSE model_health.last_success END,
                    last_failure = CASE WHEN NOT :success THEN NOW() ELSE model_health.last_failure END
            """), {"model": model, "provider": provider,
                   "success": success, "latency": float(latency or 0)})
        return {"status": "updated"}
    except Exception as e:
        print("[model_health/update] error:", e)
        return {"status": "error", "detail": str(e)}


# ──────────────────────────────────────────────────────────────
# CHAT SESSION STORAGE (server-side, cross-device persistence)
# ──────────────────────────────────────────────────────────────
import uuid as _uuid_mod

@app.get("/chat/sessions")
def list_chat_sessions():
    """List all saved chat sessions."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        try:
            rows = db.execute(text(
                "SELECT id, name, created_at, updated_at, message_count"
                " FROM chat_sessions ORDER BY updated_at DESC LIMIT 50"
            )).fetchall()
            return {"sessions": [
                {"id": r[0], "name": r[1], "created_at": str(r[2]),
                 "updated_at": str(r[3]), "message_count": r[4]}
                for r in rows
            ]}
        except Exception:
            # Table doesn't exist yet
            return {"sessions": []}
    finally:
        db.close()


@app.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str):
    """Get messages for a specific chat session."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT messages FROM chat_sessions WHERE id = :id"
        ), {"id": session_id}).fetchone()
        if not rows:
            raise HTTPException(status_code=404, detail="Session not found")
        import json as _json
        return {"session_id": session_id, "messages": _json.loads(rows[0] or "[]")}
    except HTTPException:
        raise
    except Exception as e:
        return {"session_id": session_id, "messages": [], "error": str(e)}
    finally:
        db.close()


@app.post("/chat/sessions")
async def save_chat_session(request: Request):
    """Save or update a chat session."""
    from sqlalchemy import text
    import json as _json
    body = await request.json()
    session_id = body.get("session_id") or str(_uuid_mod.uuid4())
    name       = body.get("name", "Chat Session")
    messages   = body.get("messages", [])
    msg_json   = _json.dumps(messages)
    count      = len(messages)

    db = SessionLocal()
    try:
        # Ensure table exists
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                name TEXT,
                messages TEXT,
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.execute(text("""
            INSERT INTO chat_sessions (id, name, messages, message_count, created_at, updated_at)
            VALUES (:id, :name, :msgs, :count, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                name          = :name,
                messages      = :msgs,
                message_count = :count,
                updated_at    = NOW()
        """), {"id": session_id, "name": name, "msgs": msg_json, "count": count})
        db.commit()
        return {"session_id": session_id, "status": "saved", "message_count": count}
    except Exception as e:
        print("[chat/sessions] save error:", e)
        return {"session_id": session_id, "status": "error", "detail": str(e)}
    finally:
        db.close()


@app.delete("/chat/sessions/{session_id}")
def delete_chat_session(session_id: str):
    """Delete a chat session."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM chat_sessions WHERE id = :id"), {"id": session_id})
        db.commit()
        return {"status": "deleted"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


@app.get("/metrics/model_benchmark")
def get_model_benchmark():
    """Get latest model benchmark results."""
    import json as _json
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Try from database first
        try:
            row = db.execute(text(
                "SELECT data, created_at FROM benchmark_results ORDER BY created_at DESC LIMIT 1"
            )).fetchone()
            if row:
                return _json.loads(row[0])
        except Exception:
            pass

        # Fall back to file
        report_path = "/ai-firm/data/reports/systems/model-benchmark.json"
        if os.path.exists(report_path):
            with open(report_path) as f:
                return _json.load(f)

        return {"error": "No benchmark data yet", "run_at": None, "results": [], "assignments": {}}
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


@app.post("/metrics/model_benchmark/save")
async def save_benchmark(request: Request):
    """Save benchmark results from the benchmark script."""
    import json as _json
    try:
        body = await request.json()
        # Create table if needed
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS benchmark_results (
                    id BIGSERIAL PRIMARY KEY,
                    data TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "INSERT INTO benchmark_results (data) VALUES (:d)"
            ), {"d": _json.dumps(body)})
        return {"status": "saved"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/metrics/model_benchmark/run")
def run_benchmark_now():
    """Trigger a benchmark run asynchronously."""
    import subprocess, threading
    def _run():
        try:
            subprocess.run(
                ["docker", "exec", "jarvis-orchestrator",
                 "python3", "/ai-firm/tools/model_benchmark.py"],
                timeout=300, capture_output=True
            )
        except Exception as e:
            print(f"[benchmark] run error: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"status": "benchmark_started", "message": "Check /metrics/model_benchmark in ~60s"}


@app.get("/metrics/models/summary")
def get_models_summary():
    """
    Returns model health summary from latest benchmark + historical data.
    Used by dashboard Model Health section.
    """
    import json as _json
    from sqlalchemy import text
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        # Get latest benchmark
        benchmark = {}
        report_path = "/ai-firm/data/reports/systems/model-benchmark.json"
        if os.path.exists(report_path):
            with open(report_path) as f:
                benchmark = _json.load(f)

        availability = benchmark.get("availability", {})
        assignments  = benchmark.get("assignments", {})
        role_configs = benchmark.get("role_configs", {})

        # Build role fit map from ACTUAL .env assignments (not benchmark report)
        ENV_ROLE_MAP = {
            "MODEL_JARVIS_ORCHESTRATOR": "jarvis",
            "MODEL_RESEARCH":            "research",
            "MODEL_FINANCIAL_STRATEGY":  "revenue",
            "MODEL_MARKETING":           "sales",
            "MODEL_STRATEGIC_PLANNING":  "growth",
            "MODEL_CODING":              "product",
            "MODEL_LEGAL_STRUCTURING":   "legal",
            "MODEL_SYSTEMS":             "systems",
            "MODEL_MICRO_CODING":        "code",
            "MODEL_FAST_WORKER":         "voice",
        }
        role_fit: dict = {}
        # Override jarvis role with Redis active model if set
        try:
            import redis as _rfx
            _rfxr = _rfx.from_url(
                os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
                decode_responses=True
            )
            _jmo = _rfxr.get("jarvis:model_override")
            if _jmo and _jmo.strip():
                _jmo = _jmo.strip()
                # Remove jarvis from old env-based model entry later
                _jarvis_redis_model = _jmo
            else:
                _jarvis_redis_model = None
        except Exception:
            _jarvis_redis_model = None
        # Load ALL agent overrides from Redis
        _all_redis_overrides = {}
        try:
            import redis as _rfx2
            _rfxr2 = _rfx2.from_url(
                os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
                decode_responses=True
            )
            _agent_roles = ["jarvis","research","revenue","sales","growth","product","legal","systems","code","voice"]
            for _ag in _agent_roles:
                if _ag == "jarvis":
                    _ov = _rfxr2.get("jarvis:model_override")
                else:
                    _ov = _rfxr2.get(f"agent:model_override:{_ag}")
                if _ov and _ov.strip():
                    _all_redis_overrides[_ag] = _ov.strip()
        except Exception:
            pass

        for env_var, role in ENV_ROLE_MAP.items():
            m = os.getenv(env_var, "")
            if not m:
                for r, info in assignments.items():
                    if r == role:
                        m = info.get("model", "")
            # Use Redis override for any agent if available
            if role in _all_redis_overrides:
                m = _all_redis_overrides[role]
            if m:
                if m not in role_fit:
                    role_fit[m] = []
                if role not in role_fit[m]:
                    role_fit[m].append(role)

        # Build good_for map from hardcoded role-model affinity
        # (role_configs removed from benchmark — this is the authoritative source)
        GOOD_FOR_MAP = {
            "moonshotai/kimi-k2.5":                          ["jarvis","research","legal","revenue","sales","growth"],
            "moonshotai/kimi-k2-instruct":                   ["jarvis","code","product","systems"],
            "moonshotai/kimi-k2-thinking":                   ["research","legal"],
            "qwen/qwen3-coder-480b-a35b-instruct":           ["code","product","systems"],
            "qwen/qwen3.5-397b-a17b":                        ["jarvis","research","legal","revenue","sales","growth"],
            "qwen/qwen3.5-122b-a10b":                        ["jarvis","sales","voice"],
            "meta/llama-4-maverick-17b-128e-instruct":       ["jarvis","sales","growth","product","systems","voice"],
            "meta/llama-3.3-70b-instruct":                   ["jarvis","revenue","sales","systems","voice"],
            "meta/llama-3.1-8b-instruct":                    ["voice","systems"],
            "nvidia/llama-3.3-nemotron-super-49b-v1":        ["jarvis","research","revenue","legal"],
            "nvidia/llama-3.1-nemotron-ultra-253b-v1":       ["research","legal","revenue"],
            "mistralai/mistral-large-3-675b-instruct-2512":  ["jarvis","research","legal","revenue","sales"],
            "deepseek-ai/deepseek-v3.2":                     ["research","revenue","growth"],
            "mistralai/devstral-2-123b-instruct-2512":       ["code","systems"],
            "qwen/qwen2.5-coder-32b-instruct":               ["code","systems"],
            # Anthropic
            "claude-opus-4-6":                               ["research","legal","revenue","jarvis"],
            "claude-opus-4-5":                               ["research","legal","revenue","jarvis"],
            "claude-sonnet-4-6":                             ["jarvis","research","revenue","sales","growth","product","legal"],
            "claude-sonnet-4-5":                             ["jarvis","research","revenue","sales","product"],
            "claude-haiku-4-5-20251001":                     ["voice","sales","jarvis"],
            # OpenAI
            "gpt-4.1":                                       ["jarvis","research","revenue","sales","growth","product"],
            "gpt-4.1-mini":                                  ["jarvis","sales","growth","voice"],
            "gpt-4.1-nano":                                  ["voice","sales"],
            "gpt-4o":                                        ["jarvis","research","revenue","product"],
            "gpt-4o-mini":                                   ["jarvis","sales","voice"],
            "gpt-5":                                         ["jarvis","research","legal","revenue"],
            "gpt-5.4-2026-03-05":                            ["jarvis","research","legal","revenue","product"],
            "o1":                                            ["research","legal","revenue"],
            "o3":                                            ["research","legal","revenue"],
            "o3-mini":                                       ["research","legal","code"],
            "o4-mini":                                       ["code","systems","product"],
            "codex-mini-latest":                             ["code","systems"],
        }
        model_roles: dict = {
            m: [{"role": r, "rank": i+1, "description": ""} for i, r in enumerate(roles)]
            for m, roles in GOOD_FOR_MAP.items()
        }

        # Get historical latency from model_health table
        history = {}
        try:
            rows = db.execute(text(
                "SELECT model, health_score, avg_latency_ms, success_count, failure_count, last_used"
                " FROM model_health ORDER BY last_used DESC"
            )).fetchall()
            for r in rows:
                history[r[0]] = {
                    "health_score":  round(float(r[1] or 1.0), 3),
                    "avg_latency_ms": int(r[2] or 0),
                    "success_count": int(r[3] or 0),
                    "failure_count": int(r[4] or 0),
                    "last_used":     str(r[5]) if r[5] else None,
                }
        except Exception as e:
            print("[models/summary] history error:", e)

        # Compose final model list
        models_out = []
        for model, avail in availability.items():
            short = model.split("/")[-1]
            is_available = avail.get("available", False)
            latency = avail.get("latency_ms", 9999)
            hist = history.get(model, {})

            # Compute real performance score (0-100)
            # Based on: availability, latency, historical success rate
            if not is_available:
                perf_score = 0
            else:
                # Latency score: 100 at <300ms, 0 at >10000ms
                lat_score = max(0, min(100, 100 - (latency - 300) / 97))
                # Reliability score from history
                total_calls = (hist.get("success_count", 0) + hist.get("failure_count", 0))
                rel_score = (hist.get("success_count", 0) / total_calls * 100) if total_calls > 0 else 75.0
                # Weighted: reliability matters more than raw speed
                perf_score = round(rel_score * 0.6 + lat_score * 0.4, 1)

            # Roles this model is assigned to (currently running for)
            assigned_roles = role_fit.get(model, [])
            # Roles this model is qualified for (in priority list)
            qualified_roles = [r["role"] for r in model_roles.get(model, [])]

            models_out.append({
                "model":            model,
                "short_name":       short,
                "available":        is_available,
                "latency_ms":       latency,
                "performance_score": perf_score,
                "assigned_to":      assigned_roles,
                "good_for":         qualified_roles,
                "history":          hist,
                "benchmark_run":    benchmark.get("run_at"),
            })

        # Sort: available first, then by performance score
        models_out.sort(key=lambda x: (-int(x["available"]), -x["performance_score"]))

        return {
            "models":        models_out,
            "benchmark_run": benchmark.get("run_at"),
            "total":         len(models_out),
            "available":     sum(1 for m in models_out if m["available"]),
        }
    except Exception as e:
        return {"models": [], "error": str(e)}
    finally:
        db.close()


# ── CST/CDT TIMEZONE HELPERS ──────────────────────────────────
def _cst_midnight_today():
    import datetime as _dt
    now_utc = _dt.datetime.utcnow()
    month = now_utc.month
    is_cdt = 3 <= month <= 11
    offset_hours = 5 if is_cdt else 6
    now_local = now_utc - _dt.timedelta(hours=offset_hours)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local + _dt.timedelta(hours=offset_hours)

def _cst_midnight_yesterday():
    import datetime as _dt
    return _cst_midnight_today() - _dt.timedelta(days=1)


# ── /metrics/llm/summary ──────────────────────────────────────
@app.get("/metrics/llm/summary")
def get_llm_summary():
    """Token counts for today/yesterday/month with correct CST midnight boundaries."""
    from sqlalchemy import text
    from datetime import timedelta
    db = SessionLocal()
    try:
        today_start     = _cst_midnight_today()
        yesterday_start = _cst_midnight_yesterday()
        month_start     = today_start.replace(day=1)

        def tok(since, until=None):
            try:
                if until:
                    r = db.execute(text(
                        "SELECT COALESCE(SUM(tokens_total),0), COALESCE(SUM(cost_usd),0)"
                        " FROM mcp_llm_calls WHERE created_at >= :s AND created_at < :u"
                    ), {"s": since, "u": until}).fetchone()
                else:
                    r = db.execute(text(
                        "SELECT COALESCE(SUM(tokens_total),0), COALESCE(SUM(cost_usd),0)"
                        " FROM mcp_llm_calls WHERE created_at >= :s"
                    ), {"s": since}).fetchone()
                return {"tokens": int(r[0] or 0), "cost": float(r[1] or 0)}
            except Exception as e:
                print("[llm/summary] tok error:", e)
                return {"tokens": 0, "cost": 0}

        today     = tok(today_start)
        yesterday = tok(yesterday_start, today_start)
        month     = tok(month_start)

        def by_group(since, until=None, grp="agent"):
            try:
                if until:
                    rows = db.execute(text(
                        f"SELECT {grp}, COALESCE(SUM(tokens_total),0) as tt"
                        f" FROM mcp_llm_calls WHERE created_at >= :s AND created_at < :u GROUP BY {grp} ORDER BY tt DESC"
                    ), {"s": since, "u": until}).fetchall()
                else:
                    rows = db.execute(text(
                        f"SELECT {grp}, COALESCE(SUM(tokens_total),0) as tt"
                        f" FROM mcp_llm_calls WHERE created_at >= :s GROUP BY {grp} ORDER BY tt DESC"
                    ), {"s": since}).fetchall()
                return {r[0]: {"tokens_total": int(r[1])} for r in rows if r[0]}
            except Exception:
                return {}

        # Save daily snapshot
        try:
            import json as _j
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS token_daily_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    snapshot_date DATE NOT NULL,
                    tokens_total BIGINT DEFAULT 0,
                    cost_usd DECIMAL(12,6) DEFAULT 0,
                    by_agent JSONB DEFAULT '{}'::jsonb,
                    by_model JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(snapshot_date)
                )
            """))
            by_agent_snap = by_group(today_start)
            by_model_snap = by_group(today_start, grp="model")
            db.execute(text("""
                INSERT INTO token_daily_snapshots (snapshot_date, tokens_total, cost_usd, by_agent, by_model)
                VALUES (:d, :t, :c, :a::jsonb, :m::jsonb)
                ON CONFLICT (snapshot_date) DO UPDATE SET
                    tokens_total = :t, cost_usd = :c, by_agent = :a::jsonb, by_model = :m::jsonb
            """), {
                "d": today_start.date(),
                "t": today["tokens"], "c": today["cost"],
                "a": _j.dumps(by_agent_snap), "m": _j.dumps(by_model_snap),
            })
            db.commit()
        except Exception as snap_e:
            print("[llm/summary] snapshot error:", snap_e)

        return {
            "today":              today,
            "yesterday":          yesterday,
            "month":              month,
            "by_agent_today":     by_group(today_start),
            "by_agent_yesterday": by_group(yesterday_start, today_start),
            "by_model_today":     by_group(today_start,     grp="model"),
            "by_model_yesterday": by_group(yesterday_start, today_start, grp="model"),
            "by_model_week":      by_group(today_start - timedelta(days=7), grp="model"),
        }
    except Exception as e:
        return {"error": str(e), "today": {"tokens":0,"cost":0}, "yesterday": {"tokens":0,"cost":0}, "month": {"tokens":0,"cost":0}}
    finally:
        db.close()


# ── /files/download-zip ───────────────────────────────────────
@app.get("/files/download-zip")
def download_folder_zip(path: str = ""):
    import zipfile, io, os
    from fastapi.responses import StreamingResponse
    root = "/ai-firm"
    folder = os.path.join(root, path.lstrip("/")) if path else root
    if not os.path.exists(folder):
        raise HTTPException(404, "Folder not found")
    if not os.path.isdir(folder):
        raise HTTPException(400, "Not a folder")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in [".git","node_modules","__pycache__",".next"]]
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                arcname  = os.path.relpath(filepath, folder)
                try:
                    zf.write(filepath, arcname)
                except Exception:
                    pass
    buf.seek(0)
    folder_name = os.path.basename(folder) or "silentempire"
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={folder_name}.zip"})


# ── /metrics/billing/actual ───────────────────────────────────
@app.get("/metrics/billing/actual")
def get_actual_billing():
    """Real billed costs from OpenAI org API + calculated costs for Anthropic/NVIDIA."""
    import urllib.request as _urllib
    import json as _json2
    from datetime import datetime, timedelta
    from sqlalchemy import text
    result = {"openai": None, "anthropic": None, "nvidia": None, "errors": []}

    # OpenAI — real billed cost from org API
    openai_org_key = os.getenv("OPENAI_ORG_API_KEY", "").strip()
    if openai_org_key:
        try:
            now        = int(datetime.utcnow().timestamp())
            month_start = int(datetime.utcnow().replace(day=1,hour=0,minute=0,second=0).timestamp())
            _url = f"https://api.openai.com/v1/organization/costs?start_time={month_start}&end_time={now}&interval=1d"
            _req = _urllib.Request(_url, headers={"Authorization": f"Bearer {openai_org_key}"})
            with _urllib.urlopen(_req, timeout=15) as _resp:
                d = _json2.loads(_resp.read())
            items = d.get("data", [])
            total_cents = sum(item.get("amount", {}).get("value", 0) for item in items)
            result["openai"] = {
                "month_cost_usd": round(total_cents / 100, 6),
                "source": "openai_org_api_actual",
                "line_items": len(items),
            }
        except Exception as e:
            result["errors"].append(f"OpenAI: {str(e)[:100]}")

    # Anthropic — calculated from tokens × pricing
    db = SessionLocal()
    try:
        month_start_dt = datetime.utcnow().replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        rows = db.execute(text(
            "SELECT model, SUM(tokens_in) as ti, SUM(tokens_out) as to_, SUM(tokens_total) as tt, SUM(cost_usd) as cost"
            " FROM mcp_llm_calls WHERE provider = 'anthropic' AND created_at >= :s GROUP BY model"
        ), {"s": month_start_dt}).fetchall()
        total_cost = sum(float(r[4] or 0) for r in rows)
        result["anthropic"] = {
            "month_cost_usd": round(total_cost, 6),
            "source": "calculated_from_tokens_x_pricing",
            "by_model": [{"model": r[0], "tokens": int(r[2] or 0), "cost_usd": round(float(r[4] or 0), 6)} for r in rows],
        }

        # NVIDIA free
        nv = db.execute(text(
            "SELECT COALESCE(SUM(tokens_total),0) FROM mcp_llm_calls WHERE provider = 'nvidia' AND created_at >= :s"
        ), {"s": month_start_dt}).fetchone()
        result["nvidia"] = {"month_cost_usd": 0.0, "month_tokens": int(nv[0] or 0), "source": "free_tier"}
    except Exception as e:
        result["errors"].append(f"DB: {str(e)[:100]}")
    finally:
        db.close()

    return result
