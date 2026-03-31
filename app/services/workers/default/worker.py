import time
import datetime
import redis
import socket
import uuid
import os
import json
from prometheus_client import Counter, Gauge, start_http_server

from database import SessionLocal
from models import Job, ProviderPricing, BudgetControl
from ai_engine.router import run_model

from alerts import send_telegram_alert
from models import ProviderHealth
import redis
import os

redis_client = redis.Redis(
    host="redis",
    port=6379,
    decode_responses=True
)

def log_event(*args, **kwargs):
    message = json.dumps({
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "worker_id": WORKER_ID,
        "args": args,
        "kwargs": kwargs
    })

    print(message)
    redis_client.publish("logs", message)

WORKER_ID = socket.gethostname()
redis_client = redis.Redis(host="redis", port=6379, decode_responses=True)

MAX_INPUT_TOKENS_ESTIMATE = 4000
MAX_OUTPUT_TOKENS_ESTIMATE = 4000


# ==========================================
# DYNAMIC MODEL REGISTRY (ENV DRIVEN)
# ==========================================

AGENT_MODEL_MAP = {
    "jarvis":         os.getenv("MODEL_JARVIS_ORCHESTRATOR",  "moonshotai/kimi-k2.5"),
    "research":       os.getenv("MODEL_RESEARCH",             "moonshotai/kimi-k2-thinking"),
    "revenue":        os.getenv("MODEL_FINANCIAL_STRATEGY",   "moonshotai/kimi-k2.5"),
    "sales":          os.getenv("MODEL_MARKETING",            "moonshotai/kimi-k2.5"),
    "growth":         os.getenv("MODEL_STRATEGIC_PLANNING",   "moonshotai/kimi-k2.5"),
    "product":        os.getenv("MODEL_CODING",               "moonshotai/kimi-k2-instruct"),
    "legal":          os.getenv("MODEL_LEGAL_STRUCTURING",    "moonshotai/kimi-k2-thinking"),
    "systems":        os.getenv("MODEL_SYSTEMS",              "qwen/qwen3-coder-480b-a35b-instruct"),
    "code":           os.getenv("MODEL_MICRO_CODING",         "qwen/qwen3-coder-480b-a35b-instruct"),
    "voice":          os.getenv("MODEL_FAST_WORKER",          "meta/llama-4-maverick-17b-128e-instruct"),
    "strategic_planning": os.getenv("MODEL_STRATEGIC_PLANNING", "moonshotai/kimi-k2.5"),
    "financial_strategy": os.getenv("MODEL_FINANCIAL_STRATEGY", "moonshotai/kimi-k2.5"),
    "legal_structuring":  os.getenv("MODEL_LEGAL_STRUCTURING",  "moonshotai/kimi-k2-thinking"),
    "fast_worker":        os.getenv("MODEL_FAST_WORKER",        "meta/llama-4-maverick-17b-128e-instruct"),
    "micro_coding":       os.getenv("MODEL_MICRO_CODING",       "qwen/qwen3-coder-480b-a35b-instruct"),
}


# ===============================
# METRICS
# ===============================

jobs_processed = Counter("se_jobs_processed_total", "Total jobs processed")
jobs_failed = Counter("se_jobs_failed_total", "Total jobs failed")
budget_current_spend = Gauge("se_budget_current_spend_usd", "Current daily spend")
queue_depth = Gauge("se_queue_depth", "Current Redis queue depth")


def update_queue_depth():
    try:
        depth = redis_client.llen("queue:default")
        queue_depth.set(depth)
    except Exception:
        pass


def get_pricing(db, provider, model):
    pricing = (
        db.query(ProviderPricing)
        .filter(
            ProviderPricing.provider == provider,
            ProviderPricing.model == model
        )
        .first()
    )

    if not pricing:
        raise Exception(f"No pricing configured for {provider}:{model}")

    return pricing


def estimate_max_cost(pricing):
    input_cost = (MAX_INPUT_TOKENS_ESTIMATE / 1000) * pricing.input_cost_per_1k_tokens
    output_cost = (MAX_OUTPUT_TOKENS_ESTIMATE / 1000) * pricing.output_cost_per_1k_tokens
    return round(input_cost + output_cost, 8)


# ===============================
# BUDGET CONTROL
# ===============================

def ensure_daily_budget_exists(db):

    today = datetime.datetime.utcnow().date().isoformat()

    existing = db.query(BudgetControl).filter(
        BudgetControl.date == today
    ).first()

    if existing:
        return existing

    last_budget = db.query(BudgetControl).order_by(
        BudgetControl.date.desc()
    ).first()

    if not last_budget:
        raise Exception("No historical budget configuration found.")

    new_budget = BudgetControl(
        date=today,
        daily_limit_usd=last_budget.daily_limit_usd,
        current_spend_usd=0,
        is_locked=False
    )

    db.add(new_budget)
    db.commit()

    log_event(
        "budget_rollover_created",
        date=today,
        daily_limit=new_budget.daily_limit_usd
    )

    return new_budget


def reserve_budget(db, amount):

    budget = ensure_daily_budget_exists(db)

    budget = db.query(BudgetControl).filter(
        BudgetControl.id == budget.id
    ).with_for_update().first()

    if not budget:
        raise Exception("No budget configured for today.")

    if budget.is_locked:
        raise Exception("Daily budget locked.")

    projected = budget.current_spend_usd + amount

    if projected > budget.daily_limit_usd:
        budget.is_locked = True
        db.commit()

        send_telegram_alert(
            f"🚨 SilentEmpireAI Budget Lock\n"
            f"Limit: ${budget.daily_limit_usd}\n"
            f"Current: ${budget.current_spend_usd}"
        )

        raise Exception("Daily budget exceeded (pre-check).")

    budget.current_spend_usd = projected
    db.commit()

    budget_current_spend.set(budget.current_spend_usd)

    return budget


def adjust_budget_after_execution(db, reserved_amount, actual_cost):

    budget = ensure_daily_budget_exists(db)

    budget = db.query(BudgetControl).filter(
        BudgetControl.id == budget.id
    ).with_for_update().first()

    budget.current_spend_usd -= reserved_amount
    budget.current_spend_usd += actual_cost

    db.commit()
    budget_current_spend.set(budget.current_spend_usd)


def calculate_actual_cost(pricing, tokens_input, tokens_output):

    input_cost = (tokens_input or 0) / 1000 * pricing.input_cost_per_1k_tokens
    output_cost = (tokens_output or 0) / 1000 * pricing.output_cost_per_1k_tokens

    return round(input_cost + output_cost, 8)


def run_ai_task(payload, forced_model=None):

    model_to_use = forced_model or payload.get("model")

    if not model_to_use:
        raise Exception("No model specified")

    messages = payload.get("messages")

    # --------------------------------------
    # AUTO-CONSTRUCT MESSAGES IF MISSING
    # --------------------------------------

    if not messages:
        instruction = payload.get("instruction", "")
        target = payload.get("target", "")
        product = payload.get("product", "")
        agent = payload.get("agent", "assistant")

        if instruction:
            # Split instruction into system (doctrine) + user (task) parts.
            # This prevents doctrine/identity text from triggering safety filters
            # and works universally across Anthropic, OpenAI, and NVIDIA providers.
            #
            # The instruction format from agents is:
            #   === EXECUTIVE STACK ===
            #   {doctrine}
            #   [identity/soul sections]
            #   You are the X Agent...
            #   TASK:
            #   {actual task}
            #
            # We split at TASK: so doctrine → system, task → user

            system_content = ""
            user_content = instruction

            # Try to split at TASK: marker
            task_markers = ["\nTASK:\n", "TASK:\n", "\nTASK: ", "TASK: ", "\n\nTASK:\n"]
            for marker in task_markers:
                if marker in instruction:
                    parts = instruction.split(marker, 1)
                    system_content = parts[0].strip()
                    user_content = parts[1].strip()
                    break

            if system_content:
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user",   "content": user_content}
                ]
            else:
                # No TASK: marker found — send full instruction as user message
                messages = [
                    {"role": "user", "content": instruction}
                ]
        else:
            # Fallback: bare minimum prompt
            messages = [
                {
                    "role": "system",
                    "content": f"You are the {agent} agent for SilentEmpireAI."
                },
                {
                    "role": "user",
                    "content": f"Target audience: {target}\nProduct: {product}"
                }
            ]

    # Use large timeout — let active models run as long as needed.
    # Only kills truly hung connections (5 min). Pending-stuck handled by job_runner.py.
    return run_model(
        model=model_to_use,
        messages=messages,
        timeout=300
    )

# ===============================
# PROVIDER HEALTH
# ===============================

def update_provider_health(db, provider, success):

    record = db.query(ProviderHealth).filter(
        ProviderHealth.provider == provider
    ).first()

    if not record:
        record = ProviderHealth(provider=provider)
        db.add(record)
        db.commit()
        record = db.query(ProviderHealth).filter(
            ProviderHealth.provider == provider
        ).first()

    if success:
        record.success_count += 1
    else:
        record.failure_count += 1

    total = record.success_count + record.failure_count

    if total > 0:
        record.health_score = record.success_count / total

    record.last_updated = datetime.datetime.utcnow()
    db.commit()


# ===============================
# JOB PROCESSING
# ===============================

def process_job(job_id):

    correlation_id = str(uuid.uuid4())
    db = SessionLocal()
    job = None

    try:

        job = db.query(Job).filter(Job.id == job_id).first()

        if not job:
            log_event(
                "job_not_found",
                correlation_id=correlation_id,
                job_id=str(job_id)
            )
            return

        job.status = "running"
        job.started_at = datetime.datetime.utcnow()
        db.commit()

        log_event(
            "job_started",
            correlation_id=correlation_id,
            job_id=str(job.id)
        )

        start_time = time.time()

        # ==========================================
        # AGENT-AWARE MODEL ROUTING
        # ==========================================

        # ==========================================
        # MODEL SELECTION (payload override supported)
        # ==========================================

        forced_model = job.payload.get("model")
        agent_name = job.payload.get("agent")

        if forced_model:
            model_name = forced_model
        else:
            if not agent_name:
                print("WARNING: No agent in payload. Defaulting to strategic_planning.")
                agent_name = "strategic_planning"

            # Check Redis override first (set via Mission Control UI)
            redis_override = None
            try:
                redis_override = redis_client.get(f"agent:model_override:{agent_name}")
                if redis_override:
                    redis_override = redis_override.strip()
            except Exception:
                pass

            if redis_override:
                model_name = redis_override
                print(f"INTELLIGENCE ROUTING → Redis override: {model_name}")
            else:
                model_name = AGENT_MODEL_MAP.get(
                    agent_name,
                    os.getenv("MODEL_JARVIS_ORCHESTRATOR", "deepseek-ai/deepseek-v3.2")
                )

        # Provider is determined by model prefix
        if model_name.startswith("claude") or model_name.startswith("anthropic/"):
            provider_name = "anthropic"
        elif model_name.startswith("gpt") or model_name.startswith("openai/") or model_name.startswith("o1") or model_name.startswith("o3") or model_name.startswith("o4") or model_name.startswith("codex"):
            provider_name = "openai"
        else:
            provider_name = "nvidia"

        # Normalize OpenAI model ids for pricing + provider call
        # pricing table stores "gpt-4o" not "openai/gpt-4o"
        if provider_name == "openai" and model_name.startswith("openai/"):
            model_name = model_name.split("/", 1)[1]
            job.payload["model"] = model_name

        print("INTELLIGENCE ROUTING → Agent:", agent_name if agent_name else "(forced)")
        print("INTELLIGENCE ROUTING → Model:", model_name)

        pricing = get_pricing(db, provider_name, model_name)
        max_possible_cost = estimate_max_cost(pricing)

        reserve_budget(db, max_possible_cost)
        reserved_amount = max_possible_cost

        result = run_ai_task(job.payload, forced_model=model_name)

        job.result = result.get("content") or result.get("output")
        job.provider = result.get("provider")
        job.model_used = result.get("model_used")
        job.tokens_input = result.get("tokens_in") or result.get("tokens_input")
        job.tokens_output = result.get("tokens_out") or result.get("tokens_output")

        actual_cost = calculate_actual_cost(
            pricing,
            job.tokens_input,
            job.tokens_output
        )

        adjust_budget_after_execution(db, reserved_amount, actual_cost)

        job.estimated_cost_usd = actual_cost
        job.status = "completed"
        job.completed_at = datetime.datetime.utcnow()

        db.commit()

        # ── AGENT METRICS TRACKING ──────────────────────────────────
        try:
            import requests as _req
            _api = "http://api:8000"
            _payload = job.payload or {}
            _instr = str(_payload.get("instruction", "")).lower()
            _agent = _payload.get("agent", "")
            if not _agent:
                for _ag in ["research","revenue","sales","growth","product","legal","systems","code","voice"]:
                    if f"you are the {_ag}" in _instr or f"{_ag} agent" in _instr:
                        _agent = _ag
                        break
            if not _agent: _agent = "worker"
            _ti  = job.tokens_input  or 0
            _to  = job.tokens_output or 0
            _mod = job.model_used    or ""
            _cid = str(_payload.get("chain_id", ""))
            _dur = int((time.time() - start_time) * 1000)
            if _ti or _to:
                _req.post(f"{_api}/metrics/llm/record", json={
                    "agent": _agent, "model": _mod,
                    "provider": job.provider or provider_name or "nvidia",
                    "tokens_in": _ti, "tokens_out": _to,
                    "tokens_total": _ti + _to,
                    "cost_usd": float(actual_cost or 0),
                    "chain_id": _cid,
                }, timeout=2)
                if _cid:
                    _req.post(f"{_api}/chains/{_cid}/event", json={
                        "event": "step_completed", "agent": _agent,
                        "output": f"tokens:{_ti}in/{_to}out",
                    }, timeout=2)
            # Update per-model health score
            if _mod:
                _req.post(f"{_api}/metrics/model_health/update", json={
                    "model": _mod, "provider": job.provider or "nvidia",
                    "success": True, "latency_ms": _dur,
                }, timeout=2)
        except Exception:
            pass
        # ── END AGENT METRICS TRACKING ──────────────────────────────

        jobs_processed.inc()
        update_provider_health(db, provider_name, True)

        duration_ms = int((time.time() - start_time) * 1000)

        log_event(
            "job_completed",
            correlation_id=correlation_id,
            job_id=str(job.id),
            duration_ms=duration_ms,
            estimated_cost_usd=actual_cost
        )

    except Exception as e:

        jobs_failed.inc()

        log_event(
            "job_exception",
            correlation_id=correlation_id,
            job_id=str(job_id),
            error=str(e)
        )

        if job:
            job.retry_count = (job.retry_count or 0) + 1
            job.error_message = str(e)
            job.status = "failed"
            job.completed_at = datetime.datetime.utcnow()
            db.commit()

            update_provider_health(
                db,
                provider_name if 'provider_name' in locals() else "unknown",
                False
            )

            send_telegram_alert(
                f"❌ Job Failed\n"
                f"Job ID: {job.id}\n"
                f"Error: {str(e)}"
            )

            redis_client.rpush("queue:dead", str(job.id))

    finally:
        db.close()


# ===============================
# MAIN LOOP
# ===============================

def main():
    start_http_server(8001)
    log_event("worker_started")

    while True:
        update_queue_depth()

        job_data = redis_client.brpop(["queue:orchestrator","queue:default"], timeout=5)

        if not job_data:
            continue

        raw = job_data[1]

        # Redis may return bytes
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")

        job_id = raw

        # Payload may be JSON string like {"job_id": "...", "task": "..."}
        try:
            envelope = json.loads(raw)
            if isinstance(envelope, dict) and "job_id" in envelope:
                job_id = envelope["job_id"]
        except Exception:
            pass

        # job_id may still be quoted if it was JSON-encoded as a string
        if isinstance(job_id, str) and job_id.startswith('"') and job_id.endswith('"'):
            job_id = job_id[1:-1]

        process_job(job_id)

if __name__ == "__main__":
    main()
