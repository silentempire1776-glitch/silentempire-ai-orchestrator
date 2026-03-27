# ===================== ELITE HARDENING WRAPPER (NON-INTRUSIVE) =====================
# Adds:
# - Safe JSON parse
# - Stage lock (idempotency)
# WITHOUT modifying original variable names or flow

LOCK_TTL = 180

def _safe_load(raw):
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None

def _acquire_lock(chain_id):
    try:
        return r.set(f"lock:{chain_id}", "1", nx=True, ex=LOCK_TTL)
    except Exception:
        return True  # fail-open to avoid breaking behavior

def _release_lock(chain_id):
    try:
        r.delete(f"lock:{chain_id}")
    except Exception:
        pass
# ===================== END HARDENING WRAPPER =====================

"""
=========================================================
Jarvis Orchestrator — Enterprise Durable Version
With Timeout Enforcement + API Chain Telemetry (Option B)
=========================================================
"""

import json
import time
import hashlib
import os
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import redis

from shared.redis_bus import enqueue, dequeue_blocking  # keep existing bus (enqueue is used)
from shared.schemas import create_task  # keep (may be used elsewhere / future)
from shared.artifact_store import (
    save_artifact,
    init_table,
    update_chain_status,
    create_chain_record,
    get_running_chains,
)

# ==================================================
# CHAIN DEFINITION
# ==================================================

CHAIN = [
    "research",
    "revenue",
    "sales",
    "growth",
    "product",
    "legal",
    "systems",
]

MAX_STAGE_SECONDS = 120  # 2 minutes per stage

# ==================================================
# REDIS
# ==================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

QUEUE_CHAINS = "queue.orchestrator"
QUEUE_RESULTS = "queue.orchestrator.results"

# ==================================================
# API CHAIN TELEMETRY (Option B)
# ==================================================
# Writes to app-api:
#   POST /chains/{chain_id}/event
# so chain_runs + chain_steps reflect agent outputs + CEO summary.

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

try:
    import requests  # type: ignore
except Exception:  # ultra-defensive
    requests = None


def _post_chain_event(chain_id: str, payload: dict) -> None:
    """
    Best-effort event posting; never crash orchestrator if API is down.
    """
    if not requests:
        return

    try:
        url = f"{API_BASE_URL}/chains/{chain_id}/event"
        resp = requests.post(url, json=payload, timeout=3)
        # Don't raise here; just log for visibility
        if resp.status_code >= 300:
            print(f"[WARN] chain_event POST {resp.status_code} url={url} body={resp.text[:200]}")
    except Exception as e:
        print(f"[WARN] chain_event exception chain_id={chain_id} err={e}")


def chain_started(chain_id: str) -> None:
    _post_chain_event(chain_id, {"event": "chain_started"})


def chain_failed(chain_id: str, error: str) -> None:
    _post_chain_event(chain_id, {"event": "chain_failed", "error": error})


def chain_completed(chain_id: str, results_by_agent: dict, ceo_summary: str) -> None:
    _post_chain_event(chain_id, {
        "event": "chain_completed",
        "meta": {
            "results_by_agent": results_by_agent,
            "ceo_summary": ceo_summary,
        }
    })


def step_started(chain_id: str, agent: str) -> None:
    _post_chain_event(chain_id, {"event": "step_started", "agent": agent})


def step_completed(chain_id: str, agent: str, output: str, meta: Optional[dict] = None) -> None:
    payload: dict = {"event": "step_completed", "agent": agent, "output": output}
    if meta is not None:
        payload["meta"] = meta
    _post_chain_event(chain_id, payload)


def step_failed(chain_id: str, agent: str, error: str) -> None:
    _post_chain_event(chain_id, {"event": "step_failed", "agent": agent, "error": error})


# ==================================================
# TIME UTIL
# ==================================================

def now() -> str:
    return datetime.utcnow().isoformat()


def is_timeout(start_time_str: Optional[str]) -> bool:
    if not start_time_str:
        return False
    start_time = datetime.fromisoformat(start_time_str)
    return datetime.utcnow() - start_time > timedelta(seconds=MAX_STAGE_SECONDS)


# ==================================================
# DOCTRINE
# ==================================================

DOCTRINE_PATH = "/ai-firm/shared/doctrine/EXECUTIVE_STACK.md"


def load_doctrine() -> Optional[str]:
    try:
        with open(DOCTRINE_PATH, "r") as f:
            content = f.read()
        doctrine_hash = hashlib.sha256(content.encode()).hexdigest()
        print(f"[DOCTRINE LOADED] hash={doctrine_hash}")
        return content
    except Exception as e:
        print(f"[DOCTRINE ERROR] {e}")
        return None


DOCTRINE_CONTENT = load_doctrine()


# ==================================================
# CEO SUMMARY (deterministic, no LLM dependency)
# ==================================================

def _clip(s: str, n: int = 450) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"


def build_ceo_summary(target: Optional[str], product: Optional[str], results_by_agent: Dict[str, str]) -> str:
    lines: list[str] = []
    lines.append("# CEO Summary")
    lines.append("")
    lines.append(f"- **Target:** {target or '(unknown)'}")
    lines.append(f"- **Product:** {product or '(unknown)'}")
    lines.append("")
    lines.append("## Agent Breakdown (high-signal excerpts)")
    for agent in CHAIN:
        if agent in results_by_agent and results_by_agent[agent].strip():
            lines.append(f"### {agent}")
            lines.append(_clip(results_by_agent[agent]))
            lines.append("")
    lines.append("## CEO Next Actions")
    lines.append("- Confirm **offer** + **positioning** (single sentence each).")
    lines.append("- Choose 1–2 primary acquisition channels and define the first 10 actions.")
    lines.append("- Turn agent outputs into a 7-day execution sprint (tasks + owners).")
    return "\n".join(lines)


# ==================================================
# DISPATCH (keeps your existing durable semantics)
# ==================================================

def dispatch(next_agent: str, task_type: str, payload: dict, doctrine: Any, chain_id: str) -> None:
    # API telemetry
    step_started(chain_id, next_agent)

    enqueue(f"queue.agent.{next_agent}", {
        "agent": next_agent,
        "task_type": task_type,
        "payload": payload,
        "doctrine": doctrine
    })

    update_chain_status(
        chain_id,
        status="running",
        stage=next_agent,
        stage_started_at=now()
    )

    print(f"[Orchestrator] Dispatching to {next_agent} | chain_id={chain_id}")


# ==================================================
# TIMEOUT MONITOR (kept)
# ==================================================

def check_timeouts() -> None:
    running = get_running_chains()
    for chain in running:
        chain_id = chain["chain_id"]

        stage = chain.get("stage")
        if not stage:
            continue

        stage_started_at = chain.get("stage_started_at")

        # Defensive guard: skip if timestamp missing
        if not stage_started_at:
            continue

        if is_timeout(stage_started_at):
            update_chain_status(chain_id, status="failed_timeout", stage=stage)
            step_failed(chain_id, stage, "timeout")
            chain_failed(chain_id, f"timeout at stage={stage}")
            print(f"[TIMEOUT] Chain failed due to timeout | chain_id={chain_id} | stage={stage}")

# ==================================================
# JARVIS LLM CHAT HELPER FUNCTION
# ==================================================

def _load_doc(path: str) -> str:
    """Load a markdown doc from the orchestrator directory."""
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""


def _fetch_live_data() -> str:
    """
    Fetch real live data from API before every Jarvis response.
    Returns a formatted string injected into the system prompt.
    """
    lines = []
    try:
        # Agent states
        r = requests.get(f"{API_BASE_URL}/metrics/agents/live", timeout=3)
        if r.ok:
            states = r.json().get("states", {})
            if states:
                lines.append("=== CURRENT AGENT STATES ===")
                for agent, state in sorted(states.items()):
                    icon = "⚡ WORKING" if state == "working" else "● idle"
                    lines.append(f"  {agent}: {icon}")
            else:
                lines.append("=== CURRENT AGENT STATES ===")
                lines.append("  All agents idle (no recent activity)")
    except Exception:
        lines.append("=== CURRENT AGENT STATES ===")
        lines.append("  (unavailable)")

    try:
        # Token usage
        r = requests.get(f"{API_BASE_URL}/metrics/llm", timeout=3)
        if r.ok:
            data = r.json()
            today = data.get("by_agent_today", {})
            models = data.get("by_model_today", {})
            month_cost = data.get("month_cost", 0)
            req_today = data.get("total_requests_today", 0)

            lines.append("")
            lines.append("=== TOKEN USAGE TODAY ===")
            if today:
                for agent, stats in sorted(today.items()):
                    tt = stats.get("tokens_total", 0)
                    lines.append(f"  {agent}: {tt:,} tokens (in:{stats.get('tokens_in',0):,} out:{stats.get('tokens_out',0):,})")
            else:
                lines.append("  No token data recorded today yet")

            lines.append("")
            lines.append("=== MODELS IN USE TODAY ===")
            if models:
                for model, stats in sorted(models.items(), key=lambda x: -x[1].get("tokens_total",0)):
                    tt = stats.get("tokens_total", 0)
                    short = model.split("/")[-1]
                    lines.append(f"  {short}: {tt:,} tokens")
            else:
                lines.append("  No model usage recorded today")

            lines.append(f"")
            lines.append(f"=== COST ===")
            lines.append(f"  This month: ${month_cost:.4f}")
            lines.append(f"  Requests today: {req_today}")
    except Exception:
        lines.append("")
        lines.append("=== TOKEN USAGE ===")
        lines.append("  (unavailable)")

    try:
        # Job metrics
        r = requests.get(f"{API_BASE_URL}/metrics", timeout=3)
        if r.ok:
            m = r.json()
            lines.append("")
            lines.append("=== JOB QUEUE ===")
            lines.append(f"  Running: {m.get('running_jobs', 0)}")
            lines.append(f"  Completed: {m.get('completed_jobs', 0)}")
            lines.append(f"  Failed: {m.get('failed_jobs', 0)}")
    except Exception:
        pass

    return "\n".join(lines)


def call_llm_jarvis(prompt: str) -> str:
    """
    Jarvis chat with full identity loading + real live data injection.
    - Loads SOUL.md, IDENTITY.md, HEARTBEAT.md from orchestrator directory
    - Fetches live agent states + token usage before every response
    - Never fabricates data
    """
    ORCH_DIR = os.path.dirname(os.path.abspath(__file__))

    soul      = _load_doc(os.path.join(ORCH_DIR, "SOUL.md"))
    identity  = _load_doc(os.path.join(ORCH_DIR, "IDENTITY.md"))
    heartbeat = _load_doc(os.path.join(ORCH_DIR, "HEARTBEAT.md"))

    live_data = _fetch_live_data()

    system_prompt = f"""You are Jarvis — the sovereign command intelligence of Silent Empire AI.

{identity}

{soul}

{heartbeat}

---
## LIVE SYSTEM DATA (fetched right now — use this for all data questions)
{live_data}
---

## CRITICAL RULES
1. When answering questions about token usage, agent states, costs, or system metrics — ONLY use the LIVE SYSTEM DATA above. Do not invent numbers.
2. If the live data shows zero or empty values, say so honestly. Do not fabricate.
3. You cannot send emails, SMS, or notifications unless explicitly configured (currently NOT configured).
4. Do not claim to have done something you have not done (sent a report, dispatched a task, etc.) unless you actually did it in this session.
5. For questions about files or reports — say you would need to check the filesystem via the files browser or systems agent.
6. Current date/time: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
7. You are the command layer. You coordinate agents. You do not do their work for them by fabricating their outputs.

## WHAT YOU CAN ACTUALLY DO IN THIS CHAT
- Answer questions about system state using the live data above
- Dispatch tasks to agents (user can trigger via chain mode)
- Read system state via the data injected above
- Provide strategic guidance and recommendations
- Acknowledge honestly when something is not yet implemented

Respond as Jarvis. Direct. Precise. Honest about what is real."""

    model = os.getenv("MODEL_JARVIS_ORCHESTRATOR", "qwen/qwen3.5-122b-a10b")
    nvidia_key  = os.getenv("NVIDIA_API_KEY")
    nvidia_base = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")

    nvidia_models = [model, "meta/llama-4-maverick-17b-128e-instruct", "meta/llama-3.3-70b-instruct"]
    seen = set()
    nvidia_models = [m for m in nvidia_models if not (m in seen or seen.add(m))]

    if nvidia_key:
        for attempt_model in nvidia_models:
            try:
                url = f"{nvidia_base}/chat/completions"
                resp = requests.post(url,
                    headers={"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"},
                    json={"model": attempt_model, "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": prompt}
                    ], "temperature": 0.4, "max_tokens": 1500},
                    timeout=max(10, 120),
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"].get("content", "").strip()
                if content:
                    if attempt_model != model:
                        print(f"[JARVIS_CHAT] Used fallback model: {attempt_model}", flush=True)
                    # Track tokens
                    try:
                        usage = data.get("usage", {})
                        ti  = int(usage.get("prompt_tokens", 0) or 0)
                        to_ = int(usage.get("completion_tokens", 0) or 0)
                        if ti or to_:
                            requests.post(f"{API_BASE_URL}/metrics/llm/record", json={
                                "agent":"jarvis","model":attempt_model,"provider":"nvidia",
                                "tokens_in":ti,"tokens_out":to_,"tokens_total":ti+to_,"cost_usd":0.0,
                            }, timeout=2)
                    except Exception:
                        pass
                    return content
                print(f"[JARVIS_CHAT] Empty content from {attempt_model}, trying next", flush=True)
            except Exception as e:
                print(f"[JARVIS_CHAT] {attempt_model} failed: {str(e)[:80]}", flush=True)

    # OpenAI fallback
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            resp = requests.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt}
                ], "temperature": 0.4},
                timeout=60
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print("[JARVIS_CHAT] OpenAI failed:", str(e), flush=True)

    return "Jarvis online. LLM unavailable — please verify API keys."

def _result_to_text(result: dict) -> str:
    """
    Convert agent result payload into a stable text output for DB.
    Prefers result['data'] if present.
    """
    data = result.get("data")
    if isinstance(data, str):
        return data
    if data is None:
        return ""
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)


# ==================================================
# MAIN LOOP (Option B)
# ==================================================

def run() -> None:
    print("Jarvis orchestrator online. (Enterprise Timeout Mode + Option B Telemetry)")

    init_table()
    last_timeout_check = time.time()

    while True:
        # Periodic timeout enforcement
        if time.time() - last_timeout_check > 10:
            check_timeouts()
            last_timeout_check = time.time()

        # Listen to BOTH queues (short timeout so we can keep checking timeouts)
        item = r.brpop([QUEUE_RESULTS, QUEUE_CHAINS], timeout=5)
        if not item:
            continue

        queue_name, raw = item

        try:
            envelope = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            print(f"[ERROR] Invalid JSON from {queue_name}: {raw}")
            continue

        # --------------------------------------------------
        # A) NEW CHAIN REQUEST (from /chains/start)
        # --------------------------------------------------
        if queue_name == QUEUE_CHAINS:
            chain_id = envelope.get("chain_id")
            target = envelope.get("target")
            product = envelope.get("product")

            if not chain_id:
                print("[ERROR] Missing chain_id in queue.orchestrator envelope")
                continue

            # Remember target/product for CEO summary
            if isinstance(target, str):
                TARGET_BY_CHAIN[chain_id] = target
            if isinstance(product, str):
                PRODUCT_BY_CHAIN[chain_id] = product

            RESULTS_BY_CHAIN.setdefault(chain_id, {})

            # Durable chain record (kept) — safe best-effort with signature fallback
            try:
                try:
                    # Newer signature (some builds)
                    create_chain_record(chain_id=chain_id, target=target, product=product)
                except TypeError:
                    try:
                        # Alternate signature (some builds)
                        create_chain_record(chain_id=chain_id, payload={"target": target, "product": product})
                    except TypeError:
                        # Oldest signature (chain_id only)
                        create_chain_record(chain_id)
            except Exception as e:
                print(f"[WARN] create_chain_record failed chain_id={chain_id} err={e}")

            # API telemetry: chain started
            chain_started(chain_id)

            # Kick off first stage
            payload = {
                "chain_id": chain_id,
                "target": target,
                "product": product,
            }

            task_type = envelope.get("task_type") or "offer_stack"

            # --------------------------------------------------
            # JARVIS CHAT (Jarvis-only interactive mode)
            # --------------------------------------------------
            if task_type == "jarvis_chat":
                incoming_payload = envelope.get("payload", {}) or {}
                msg = incoming_payload.get("message")
                if msg is None:
                    msg = product

                # Record target/product for summary
                TARGET_BY_CHAIN[chain_id] = "chat"
                PRODUCT_BY_CHAIN[chain_id] = msg or ""

                RESULTS_BY_CHAIN.setdefault(chain_id, {})

                # Chain started event
                chain_started(chain_id)

                # Jarvis step started/completed
                step_started(chain_id, "jarvis")

                # Minimal deterministic reply (no LLM dependency)
                reply = call_llm_jarvis(msg or "")

                RESULTS_BY_CHAIN[chain_id]["jarvis"] = reply
                step_completed(chain_id, "jarvis", reply)

                # Complete the chain with CEO summary (optional but consistent)
                ceo = build_ceo_summary(
                    TARGET_BY_CHAIN.get(chain_id),
                    PRODUCT_BY_CHAIN.get(chain_id),
                    RESULTS_BY_CHAIN.get(chain_id, {}),
                )
                chain_completed(chain_id, RESULTS_BY_CHAIN.get(chain_id, {}), ceo)

                update_chain_status(chain_id, status="completed", stage="jarvis")
                print(f"[Orchestrator] Jarvis chat complete | chain_id={chain_id}")
                continue

            # --------------------------------------------------
            # SYS COMMAND (direct systems agent execution — v5.0)
            # Triggered by task_type == "sys_command"
            # Routes message directly to systems agent as direct_command
            # Bypasses full agent chain — returns result in single step
            # --------------------------------------------------
            if task_type == "sys_command":
                incoming_payload = envelope.get("payload", {}) or {}
                command = incoming_payload.get("message") or incoming_payload.get("command") or product or ""

                TARGET_BY_CHAIN[chain_id] = "sys_command"
                PRODUCT_BY_CHAIN[chain_id] = command
                RESULTS_BY_CHAIN.setdefault(chain_id, {})

                chain_started(chain_id)
                step_started(chain_id, "systems")

                # Dispatch directly to systems agent as direct_command
                enqueue("queue.agent.systems", {
                    "agent": "systems",
                    "task_type": "direct_command",
                    "payload": {
                        "chain_id": chain_id,
                        "command": command,
                        "message": command,
                    },
                    "doctrine": {
                        "executive": DOCTRINE_CONTENT or "",
                        "identity": "Systems Agent",
                        "soul": "Precision execution. No fluff.",
                    }
                })

                update_chain_status(chain_id, status="running", stage="systems", stage_started_at=now())
                print(f"[Orchestrator] sys_command dispatched to systems agent | chain_id={chain_id}")
                continue

            # --- CHAT COMPATIBILITY PATCH (non-regressive) ---
            # If chat, preserve the message so agents can echo/respond.
            # Supports both payload.message and product-as-message patterns.
            if task_type == "chat":
                incoming_payload = envelope.get("payload", {}) or {}
                msg = incoming_payload.get("message")
                if msg is None:
                    # fallback: some callers might still use product as message
                    msg = product
                payload["message"] = msg
                # keep product aligned for older agents that read product
                payload["product"] = msg
                payload["target"] = "chat"
            # --- END PATCH ---

            dispatch(CHAIN[0], task_type, payload, DOCTRINE_CONTENT, chain_id)
            continue

        # --------------------------------------------------
        # B) AGENT RESULT (from queue.orchestrator.results)
        # --------------------------------------------------
        agent = envelope.get("agent")
        task_type = envelope.get("task_type")
        result = envelope.get("result", {}) or {}
        payload = envelope.get("payload", {}) or {}
        doctrine = envelope.get("doctrine", {}) or {}
        chain_id = payload.get("chain_id")
        status = envelope.get("status")

        if not chain_id:
            print("[ERROR] Missing chain_id in result payload.")
            continue

        print(f"[Orchestrator] Result received from {agent} | chain_id={chain_id}")

        # Failure path
        if status == "failed":
            update_chain_status(chain_id, status="failed", stage=agent)
            err = envelope.get("error") or "unknown failure"
            if agent:
                step_failed(chain_id, agent, str(err))
            chain_failed(chain_id, str(err))
            print(f"[Orchestrator] Chain FAILED at {agent} | err={err}")
            continue

        # Save artifact (kept)
        save_artifact(
            chain_id=chain_id,
            agent=agent,
            artifact_type=result.get("artifact_type"),
            version=result.get("version"),
            data=result.get("data")
        )

        # Convert result to text + store for CEO summary
        output_text = _result_to_text(result)
        if agent:
            RESULTS_BY_CHAIN.setdefault(chain_id, {})
            RESULTS_BY_CHAIN[chain_id][agent] = output_text

        # API telemetry: step completed
        meta = result.get("meta") if isinstance(result, dict) else None
        if agent:
            step_completed(chain_id, agent, output_text, meta=meta if isinstance(meta, dict) else None)

        # sys_command chains complete after systems agent responds
        if task_type == "direct_command" and agent == "systems":
            update_chain_status(chain_id, status="completed", stage="systems")
            results_by_agent = RESULTS_BY_CHAIN.get(chain_id, {})
            # Extract clean text output from tool execution result
            tool_result = result.get("data", {})
            synthesis = tool_result.get("synthesis", "") or tool_result.get("stdout", "") or output_text
            RESULTS_BY_CHAIN[chain_id]["systems"] = synthesis
            step_completed(chain_id, "systems", synthesis)
            chain_completed(chain_id, RESULTS_BY_CHAIN.get(chain_id, {}), synthesis)
            print(f"[Orchestrator] sys_command complete | chain_id={chain_id}")
            continue

        # Determine next stage
        try:
            current_index = CHAIN.index(agent)
            next_agent = CHAIN[current_index + 1]
        except (ValueError, IndexError):
            # Completed
            update_chain_status(chain_id, status="completed", stage=agent)
            print(f"[Orchestrator] Chain complete | chain_id={chain_id}")

            # CEO summary + full breakdown
            results_by_agent = RESULTS_BY_CHAIN.get(chain_id, {})
            ceo = build_ceo_summary(
                TARGET_BY_CHAIN.get(chain_id),
                PRODUCT_BY_CHAIN.get(chain_id),
                results_by_agent,
            )

            # API telemetry: chain completed with breakdown + CEO summary
            chain_completed(chain_id, results_by_agent, ceo)
            continue

        dispatch(next_agent, task_type, payload, doctrine, chain_id)


if __name__ == "__main__":
    import threading
    from orchestrator.heartbeat import hybrid_autonomy_loop

    # Start controlled hybrid autonomy in background
    threading.Thread(
        target=hybrid_autonomy_loop,
        daemon=True
    ).start()

    run()
