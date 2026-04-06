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
import re
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

    # Always reload doctrine fresh so file updates take effect without restart
    fresh_doctrine = load_doctrine() or doctrine

    enqueue(f"queue.agent.{next_agent}", {
        "agent": next_agent,
        "task_type": task_type,
        "payload": payload,
        "doctrine": fresh_doctrine
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
    try:
        with open(path, "r") as f: return f.read()
    except Exception: return ""

def _fetch_live_data() -> str:
    lines = []
    try:
        r2 = requests.get(f"{API_BASE_URL}/metrics/agents/live", timeout=3)
        if r2.ok:
            states = r2.json().get("states", {})
            # All known agents - show even if no recent events
            all_agents = ["jarvis","research","revenue","sales","growth","product","legal","systems","code","voice"]
            jarvis_model = _get_active_jarvis_model()
            lines.append(f"=== JARVIS CURRENT MODEL: {jarvis_model} ===")
            # Show all agent models (from Redis overrides + env defaults)
            try:
                import redis as _rlive
                _rlr = _rlive.from_url(
                    os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
                    decode_responses=True
                )
                _agent_defaults = {
                    "research": os.getenv("MODEL_RESEARCH",           "moonshotai/kimi-k2-thinking"),
                    "revenue":  os.getenv("MODEL_FINANCIAL_STRATEGY", "moonshotai/kimi-k2.5"),
                    "sales":    os.getenv("MODEL_MARKETING",          "moonshotai/kimi-k2.5"),
                    "growth":   os.getenv("MODEL_STRATEGIC_PLANNING", "moonshotai/kimi-k2.5"),
                    "product":  os.getenv("MODEL_CODING",             "moonshotai/kimi-k2-instruct"),
                    "legal":    os.getenv("MODEL_LEGAL_STRUCTURING",  "moonshotai/kimi-k2-thinking"),
                    "systems":  os.getenv("MODEL_SYSTEMS",            "qwen/qwen3-coder-480b-a35b-instruct"),
                    "code":     os.getenv("MODEL_MICRO_CODING",       "qwen/qwen3-coder-480b-a35b-instruct"),
                    "voice":    os.getenv("MODEL_FAST_WORKER",        "meta/llama-4-maverick-17b-128e-instruct"),
                }
                lines.append("=== AGENT MODELS ===")
                for _ag, _default in _agent_defaults.items():
                    _ov = _rlr.get(f"agent:model_override:{_ag}")
                    _m = (_ov.strip() if _ov and _ov.strip() else _default).split("/")[-1]
                    lines.append(f"  {_ag}: {_m}{'  [override]' if _ov and _ov.strip() else ''}")
            except Exception:
                pass
            lines.append("=== AGENT STATES ===")
            for ag in all_agents:
                st = states.get(ag, "idle")
                lines.append(f"  {ag}: {'WORKING' if st=='working' else 'idle'}")
    except Exception:
        lines.append("=== AGENT STATES: (unavailable) ===")
    try:
        r3 = requests.get(f"{API_BASE_URL}/metrics/llm", timeout=3)
        if r3.ok:
            d = r3.json()
            today = d.get("by_agent_today", {})
            lines.append("=== TOKEN USAGE TODAY ===")
            if today:
                for ag, s in sorted(today.items()):
                    lines.append(f"  {ag}: {s.get('tokens_total',0):,} tokens")
            else:
                lines.append("  No token data yet today")
            lines.append(f"  Month cost: ${d.get('month_cost',0):.4f} | Requests today: {d.get('total_requests_today',0)}")
    except Exception:
        lines.append("=== TOKEN USAGE: (unavailable) ===")
    return "\n".join(lines)

def _get_model_tier(model_name: str) -> int:
    """Return prompt complexity tier for a given model."""
    tiers = {
        "claude-sonnet-4-6": 1, "claude-opus-4-6": 1, "claude-haiku-4-5": 2,
        "kimi-k2-thinking": 1, "kimi-k2-thinking": 1,
        "deepseek-v3.2": 1, "deepseek": 1,
        "nemotron-super": 1, "nemotron": 1,
        "qwen3.5-397b": 1, "397b": 1,
        "kimi-k2.5": 2, "kimi-k2-instruct": 2,
        "gpt-4.1": 2, "gpt-4o": 2, "mistral-large": 2,
        "qwen3-coder": 2, "qwen3": 2,
        "llama-4-maverick": 3, "llama-3.3-70b": 3, "llama-3.1-8b": 3,
        "maverick": 3, "70b": 3, "8b": 3,
    }
    model_lower = model_name.lower()
    for key, tier in tiers.items():
        if key in model_lower:
            return tier
    return 2  # default to balanced


def _build_jarvis_prompt() -> str:
    """Build model-optimized system prompt based on active model tier."""
    from datetime import datetime as _dt
    import os as _os

    d = _os.path.dirname(_os.path.abspath(__file__))
    active_model = _os.getenv("MODEL_JARVIS_ORCHESTRATOR", "moonshotai/kimi-k2.5")
    tier = _get_model_tier(active_model)

    # Always load these
    live   = _fetch_live_data()
    memory = _read_jarvis_memory()
    now    = _dt.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Session state (from persistent memory)
    session_state = ""
    try:
        ss_path = "/ai-firm/data/memory/jarvis/SESSION-STATE.md"
        if _os.path.exists(ss_path):
            with open(ss_path) as _f:
                session_state = _f.read()[:800]
    except Exception:
        pass

    mem_section = f"\n--- MEMORY ---\n{memory[:600]}\n---" if memory else ""
    session_section = f"\n--- SESSION ---\n{session_state}\n---" if session_state else ""
    # Fetch recent conversation history from chat sessions API
    conv_section = ""
    try:
        import requests as _creq, os as _cos
        _api = _cos.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
        _sr = _creq.get(f"{_api}/sessions", timeout=3)
        if _sr.ok:
            _resp_json = _sr.json()
            _sessions = _resp_json.get("sessions", _resp_json) if isinstance(_resp_json, dict) else _resp_json
            if _sessions:
                _sid = _sessions[0].get("id")
                if _sid:
                    _mr = _creq.get(f"{_api}/sessions/{_sid}", timeout=3)
                    if _mr.ok:
                        _msgs = _mr.json().get("messages", [])
                        _recent = [m for m in _msgs if m.get("role") in ("user","assistant")][-16:]
                        if _recent:
                            _lines = []
                            for _m in _recent:
                                _role = "Curtis" if _m["role"] == "user" else "Jarvis"
                                _text = str(_m.get("content",""))[:300]
                                _lines.append(f"{_role}: {_text}")
                            conv_section = "\n--- RECENT CONVERSATION ---\n" + "\n".join(_lines) + "\n---"
    except Exception:
        pass

    # ── TIER 1: Full doctrine for reasoning/large models ──────────
    if tier == 1:
        constitution     = _load_doc(_os.path.join(d, "CONSTITUTION.md"))
        soul             = _load_doc(_os.path.join(d, "SOUL.md"))
        identity         = _load_doc(_os.path.join(d, "IDENTITY.md"))
        heartbeat        = _load_doc(_os.path.join(d, "HEARTBEAT.md"))
        user             = _load_doc(_os.path.join(d, "USER.md"))
        elite_council    = _load_doc(_os.path.join(d, "ELITE-COUNCIL.md"))
        governance       = _load_doc(_os.path.join(d, "GOVERNANCE.md"))
        revenue_playbook = _load_doc(_os.path.join(d, "REVENUE-PLAYBOOK.md"))
        intelligence     = _load_doc(_os.path.join(d, "INTELLIGENCE.md"))

        return f"""You are Jarvis — sovereign COO and command intelligence of Silent Empire AI.

{constitution}
{identity}
{soul}
{user}
{heartbeat}

--- STRATEGIC DOCTRINE (apply silently) ---
{elite_council}
{governance}
{revenue_playbook}
{intelligence}
--- END DOCTRINE ---

--- TOOLS — USE THESE EXACT TAG FORMATS (no plain bash) ---
Web search: [EXEC:bash]python3 /ai-firm/tools/ddg_search.py "query"[/EXEC]
Perplexity: [EXEC:bash]python3 /ai-firm/tools/perplexity_search.py "query"[/EXEC]
Read file: [EXEC:bash]test -f /ai-firm/data/reports/agent/file.md && cat /ai-firm/data/reports/agent/file.md || echo "NOT FOUND"[/EXEC]
List directory: [EXEC:bash]ls /ai-firm/tools/[/EXEC]
CRITICAL PATH MAPPING: Inside this container, /srv/silentempire/ai-firm/ = /ai-firm/ — ALWAYS use /ai-firm/ paths in EXEC commands, NEVER /srv/silentempire/ai-firm/
Claude Code: [EXEC:bash]python3 /ai-firm/tools/claude_code.py "instruction" --dir /target/dir[/EXEC]
ClickUp find list: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py find-list "List Name"[/EXEC]
ClickUp list all: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py list-all[/EXEC]
ClickUp tasks: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py list-tasks LIST_ID[/EXEC]
ClickUp create task: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py create-task LIST_ID "Title"[/EXEC]
ClickUp post comment: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py post-comment TASK_ID "comment"[/EXEC]
ClickUp complete: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py complete-task TASK_ID[/EXEC]
Google Drive list folder: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py drive-list-folder FOLDER_ID[/EXEC]
Google Drive search: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py drive-search "query"[/EXEC]
Google Drive upload file: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py drive-upload /path/to/file.md FOLDER_ID[/EXEC]
Google Drive create doc from file: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py drive-create-doc /path/to/file.md "Doc Title" FOLDER_ID[/EXEC]
Google Drive save agent report: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py agent-save AGENT_NAME /path/to/file.md "Report Title"[/EXEC]
Google Drive read doc: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py drive-read-doc FILE_ID[/EXEC]
Google Drive get link: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py drive-link FILE_ID[/EXEC]
Google Drive create folder: [EXEC:bash]python3 /ai-firm/tools/google_drive_cli.py drive-mkdir "Folder Name" PARENT_ID[/EXEC]
Dispatch agent: [DISPATCH:agent-name]Full instruction with save path[/DISPATCH]

## SMART DISPATCH — SELECT 1-3 AGENTS ONLY
Match the task to the agent. Never dispatch agents that have no role in the task.
research → market research, data, trends, competitor analysis, reports
revenue  → pricing, offers, monetization, LTV, financial strategy
sales    → copy, scripts, conversion, objection handling, close sequences
growth   → channels, funnels, paid acquisition, organic, scaling
legal    → compliance, risk, contracts, disclaimers, jurisdiction
product  → roadmap, features, delivery, client journey, implementation
code     → build tools, write scripts, automation, technical implementation
systems  → server, bash, infrastructure, deployment

EXAMPLES:
- 'Write a sales email' → sales only
- 'Build a pricing page' → sales + revenue
- 'Research competitors' → research only
- 'Create a full go-to-market plan' → research + sales + growth
- 'What are the legal risks of X' → legal only

NEVER dispatch all agents. NEVER dispatch an agent unless the task requires their specialty.
CRITICAL: ALWAYS use [EXEC:bash] tags — NEVER write plain bash commands in your response.
CRITICAL: EXEC failure = report exact error verbatim, never invent output or fake success.
CRITICAL: File not found = say so exactly, never invent file contents.
--- END TOOLS ---

--- TOOL EXECUTION RULES — NON-NEGOTIABLE ---
1. NEVER fabricate a <tool_response> block. If the bash output shows Exit 1 or an error,
   report the actual error to the user. Do NOT invent a success response.
2. If a command returns "Exit 1: Commands: ..." that means you used the WRONG command name.
   Stop immediately, check the TOOLS list above for the correct command, and retry.
3. If a tool says "File not found" or "No module named X", that is a real error — do NOT
   pretend the operation succeeded.
4. Every [EXEC:bash] block must be followed by showing the ACTUAL output to the user.
   Never skip showing the output.
5. If you are unsure which command to use, run --help first:
   [EXEC:bash]python3 /ai-firm/tools/TOOLNAME.py --help 2>&1 | head -20[/EXEC]
--- END TOOL EXECUTION RULES ---


--- LIVE SYSTEM DATA ---
{live}
Current time: {now}
---
{mem_section}
{session_section}
{conv_section}
"""

    # ── TIER 2: Balanced prompt for strong general models ─────────
    elif tier == 2:
        return f"""You are Jarvis — autonomous COO of Silent Empire AI.

## WHO YOU ARE
- Sovereign command intelligence for Curtis Proske (Founder)
- Mission: Build Silent Empire to $1K/day → $10K/day
- Tone: Calm, intelligent, slightly British, light dry wit
- Style: Artifact-first, zero theater, no narration

## LAWS (follow exactly)
1. Deliver results, not progress narration
2. No ETAs, "starting now", or time theater
3. Never fabricate — if EXEC fails, say so exactly
4. Assumptions over stalling — mark assumptions clearly
5. Escalate ONLY for: legal exposure, external spend, irreversible public action

## TOOLS — USE THESE EXACT COMMANDS
Web search: [EXEC:bash]python3 /ai-firm/tools/ddg_search.py "query"[/EXEC]
Perplexity (when asked): [EXEC:bash]python3 /ai-firm/tools/perplexity_search.py "query"[/EXEC]
ClickUp find list ID: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py find-list "List Name"[/EXEC]
ClickUp list all: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py list-all[/EXEC]
ClickUp tasks: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py list-tasks LIST_ID[/EXEC]
ClickUp post comment: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py post-comment TASK_ID "comment text"[/EXEC]
ClickUp get comments: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py get-comments TASK_ID[/EXEC]
ClickUp create task: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py create-task LIST_ID "Title"[/EXEC]
CRITICAL: Always run find-list first to get LIST_ID — never guess or hardcode list IDs.
ClickUp complete: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py complete-task TASK_ID[/EXEC]
Read file: [EXEC:bash]test -f /ai-firm/data/reports/agent/file.md && cat /ai-firm/data/reports/agent/file.md || echo "NOT FOUND"[/EXEC]
List directory: [EXEC:bash]ls /ai-firm/tools/[/EXEC]
CRITICAL PATH MAPPING: Inside this container, /srv/silentempire/ai-firm/ = /ai-firm/ — ALWAYS use /ai-firm/ paths in EXEC commands, NEVER /srv/silentempire/ai-firm/
Claude Code: [EXEC:bash]python3 /ai-firm/tools/claude_code.py "instruction" --dir /target/dir[/EXEC]
Dispatch agent: [DISPATCH:agent-name]Full instruction with save path[/DISPATCH]

## SMART DISPATCH — SELECT 1-3 AGENTS ONLY
research → market research, data, reports
revenue  → pricing, offers, monetization
sales    → copy, scripts, conversion
growth   → channels, funnels, marketing
legal    → compliance, risk, contracts
product  → roadmap, features, delivery
code     → build tools, write scripts
systems  → server, bash, infrastructure

## HONESTY RULES
- EXEC failure = report exact error, never invent output
- File not found = say so, never invent contents
- No docker logs available inside your container
- Check files with EXEC, not by memory

## BUSINESS CONTEXT
- Product: Silent Vault Trust system (irrevocable non-grantor trusts, SLAT dynasty trusts)
- Primary market: Men 35-55, $120K+/year income, asset protection, divorce protection
- Secondary: Young men 24-38, college-educated
- ClickUp Current Sprint: list ID 901710993025

--- LIVE SYSTEM DATA ---
{live}
Current time: {now}
---
{mem_section}
{session_section}
{conv_section}
"""

    # ── TIER 3: Lean imperative for fast/small models ─────────────
    else:
        return f"""You are Jarvis, COO of Silent Empire AI. Serve Curtis Proske (Founder).

RULES:
- Deliver results immediately, no narration
- Never fabricate — report exact errors
- Use tools via EXEC tags, dispatch via DISPATCH tags
- Select only needed agents (1-3 max)

TOOLS:
Search: [EXEC:bash]python3 /ai-firm/tools/ddg_search.py "query"[/EXEC]
ClickUp find list ID: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py find-list "List Name"[/EXEC]
ClickUp list all: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py list-all[/EXEC]
ClickUp tasks: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py list-tasks LIST_ID[/EXEC]
ClickUp post comment: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py post-comment TASK_ID "comment text"[/EXEC]
ClickUp get comments: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py get-comments TASK_ID[/EXEC]
ClickUp create task: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py create-task LIST_ID "Title"[/EXEC]
CRITICAL: Always run find-list first to get LIST_ID — never guess or hardcode list IDs.
ClickUp complete: [EXEC:bash]python3 /ai-firm/tools/clickup_cli.py complete-task TASK_ID[/EXEC]
Claude Code: [EXEC:bash]python3 /ai-firm/tools/claude_code.py "instruction" --dir /target/dir[/EXEC]
File: [EXEC:bash]cat /ai-firm/data/reports/AGENT/file.md[/EXEC]
Agent: [DISPATCH:name]instruction with save path[/DISPATCH]

AGENTS: research, revenue, sales, growth, legal, product, code, systems
BUSINESS: Trust business — asset protection for men $120K+/year

--- LIVE DATA ---
{live}
Time: {now}
---
{mem_section}
"""


# PATCH7_ACTIVE_SESSION
def _get_active_session_id() -> str:
    """Get the most recently active session ID from the database."""
    try:
        resp = requests.get(f"{API_BASE_URL}/sessions", timeout=5)
        if resp.ok:
            sessions = resp.json()
            if sessions and isinstance(sessions, list):
                # Most recently updated session
                latest = max(sessions, key=lambda s: s.get("updated_at", ""), default=None)
                if latest:
                    return latest.get("id", "")
    except Exception:
        pass
    return ""


def _write_session_reply(session_id: str, message: str) -> None:
    """Write a message to a session (for Mission Control display)."""
    if not session_id:
        return
    try:
        requests.post(
            f"{API_BASE_URL}/sessions/{session_id}/messages",
            json={"role": "assistant", "content": message},
            timeout=10
        )
    except Exception as e:
        print(f"[AUTONOMY] Session write failed: {e}", flush=True)


def _read_jarvis_memory() -> str:
    """Read Jarvis persistent memory file."""
    try:
        path = "/ai-firm/data/memory/jarvis/core.md"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
        return ""
    except Exception:
        return ""


def _write_jarvis_memory(content: str) -> None:
    """Append to Jarvis persistent memory."""
    try:
        path = "/ai-firm/data/memory/jarvis/core.md"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            from datetime import datetime as _dt
            f.write(f"\n---\n[{_dt.utcnow().strftime('%Y-%m-%d %H:%M UTC')}]\n{content}\n")
    except Exception as e:
        print(f"[MEMORY] Write failed: {e}")


def _save_chain_report(chain_id: str, topic: str, ceo_summary: str, results: dict) -> str:
    """Save full chain output to /ai-firm/data/reports/chains/"""
    try:
        from datetime import datetime as _dt
        date_str = _dt.utcnow().strftime("%Y-%m-%d_%H-%M")
        safe_topic = topic.replace(" ", "-").replace("/", "-")[:40].lower() if topic else "chain"
        filename = f"{date_str}_{safe_topic}.md"
        path = f"/ai-firm/data/reports/chains/{filename}"
        os.makedirs(os.path.dirname(path), exist_ok=True)

        content = f"# Chain Report: {topic or chain_id}\n"
        content += f"**Date:** {_dt.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        content += f"**Chain ID:** {chain_id}\n\n"
        content += f"## CEO Summary\n{ceo_summary}\n\n"
        content += "## Agent Outputs\n"
        for agent, output in results.items():
            content += f"\n### {agent.title()}\n{output}\n"

        with open(path, "w") as f:
            f.write(content)
        return f"/ai-firm/data/reports/chains/{filename}"
    except Exception as e:
        print(f"[REPORT] Save failed: {e}")
        return ""


def _get_active_jarvis_model() -> str:
    """
    Get the active Jarvis model. Checks Redis override first,
    then falls back to env var. This allows UI model changes to
    take effect without restarting the container.
    """
    try:
        import redis as _redis_mod
        _r = _redis_mod.from_url(
            os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
            decode_responses=True
        )
        override = _r.get("jarvis:model_override")
        if override and override.strip():
            return override.strip()
    except Exception:
        pass
    return os.getenv("MODEL_JARVIS_ORCHESTRATOR", "moonshotai/kimi-k2.5")

def call_llm_jarvis(prompt: str) -> str:
    """
    Smart provider routing:
    - claude-* → Anthropic API
    - gpt-* / o1 / o3 / o4 / codex → OpenAI API
    - everything else → NVIDIA Integrate API
    Fallback chain: primary model → llama-4-maverick → llama-3.3-70b → gpt-4.1
    """
    model = _get_active_jarvis_model()
    system_prompt = _build_jarvis_prompt()
    model_lower = model.lower()

    def _record_tokens(agent, m, provider, data):
        try:
            usage = data.get("usage", {})
            ti  = int(usage.get("prompt_tokens", 0) or 0)
            to_ = int(usage.get("completion_tokens", 0) or 0)
            if ti or to_:
                requests.post(f"{API_BASE_URL}/metrics/llm/record",
                    json={"agent": agent, "model": m, "provider": provider,
                          "tokens_in": ti, "tokens_out": to_,
                          "tokens_total": ti + to_, "cost_usd": 0.0},
                    timeout=2)
        except Exception:
            pass

    def _process_content(content):
        content = content.strip()
        try:
            content, _exec_results = jarvis_process_exec_tags(content, _current_chain_id)
            if _exec_results:
                print(f"[JARVIS] Executed {len(_exec_results)} autonomous actions", flush=True)
        except Exception as _etag:
            print(f"[JARVIS] Exec tag error: {_etag}", flush=True)
        return content

    # ── ANTHROPIC (claude-*) ──────────────────────────────────────
    if "claude" in model_lower:
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            try:
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "max_tokens": 4096,
                    "temperature": 0.15,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": prompt}],
                }
                r = requests.post(url, headers=headers, json=payload, timeout=(5, 30))
                r.raise_for_status()
                data = r.json()
                content = data.get("content", [{}])[0].get("text", "").strip()
                # PATCH_JARVIS_COST_TRACKING
                if content:
                    print(f"[JARVIS_CHAT] Using Anthropic: {model}", flush=True)
                    try:
                        usage = data.get("usage", {})
                        ti  = int(usage.get("input_tokens", 0) or 0)
                        to_ = int(usage.get("output_tokens", 0) or 0)
                        if ti or to_:
                            # Calculate real cost from provider_pricing table
                            _cost = 0.0
                            try:
                                _pr = requests.get(
                                    f"{API_BASE_URL}/metrics/models/summary",
                                    timeout=2
                                )
                                # Fallback: use known Anthropic pricing
                                _pricing = {
                                    "claude-sonnet-4-6": (0.003, 0.015),
                                    "claude-haiku-4-5-20251001": (0.00025, 0.00125),
                                    "claude-opus-4-6": (0.015, 0.075),
                                    "claude-sonnet-4-5": (0.003, 0.015),
                                }
                                _model_key = model.lower()
                                _in_price, _out_price = _pricing.get(_model_key, (0.003, 0.015))
                                _cost = (ti / 1000 * _in_price) + (to_ / 1000 * _out_price)
                            except Exception:
                                _cost = (ti / 1000 * 0.003) + (to_ / 1000 * 0.015)
                            requests.post(f"{API_BASE_URL}/metrics/llm/record",
                                json={"agent": "jarvis", "model": model, "provider": "anthropic",
                                      "tokens_in": ti, "tokens_out": to_,
                                      "tokens_total": ti + to_, "cost_usd": round(_cost, 8)},
                                timeout=2)
                            # Also record in jobs table for budget tracking
                            try:
                                # Include user message and Jarvis response for Kanban visibility
                                requests.post(f"{API_BASE_URL}/jobs",
                                    json={
                                        "type": "jarvis_chat",
                                        "payload": {
                                            "agent": "jarvis",
                                            "model": model,
                                            "messages": [{"role": "user", "content": prompt}],
                                        },
                                        "result": str(content)[:8000] if content else "",
                                    },
                                    timeout=2
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass
                    return _process_content(content)
                print(f"[JARVIS_CHAT] Anthropic returned empty, falling back", flush=True)
            except Exception as e:
                print(f"[JARVIS_CHAT] Anthropic {model} failed: {str(e)[:100]}", flush=True)
        else:
            print("[JARVIS_CHAT] No ANTHROPIC_API_KEY — cannot use Claude", flush=True)
        # Fall through to NVIDIA fallback chain
        model = "meta/llama-4-maverick-17b-128e-instruct"

    # ── OPENAI (gpt-*, o1, o3, o4, codex) ────────────────────────
    elif any(x in model_lower for x in ["gpt-", "o1", "o3", "o4-", "codex"]) and "/" not in model:
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                }
                r = requests.post(url, headers=headers, json=payload, timeout=(5, 30))
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"].get("content", "").strip()
                if content:
                    print(f"[JARVIS_CHAT] Using OpenAI: {model}", flush=True)
                    _record_tokens("jarvis", model, "openai", data)
                    return _process_content(content)
                print(f"[JARVIS_CHAT] OpenAI {model} empty, falling back", flush=True)
            except Exception as e:
                print(f"[JARVIS_CHAT] OpenAI {model} failed: {str(e)[:100]}", flush=True)
        else:
            print("[JARVIS_CHAT] No OPENAI_API_KEY", flush=True)
        # Fall through to NVIDIA fallback chain
        model = "meta/llama-4-maverick-17b-128e-instruct"

    # ── NVIDIA (kimi, deepseek, qwen, llama, mistral, nemotron) ──
    nvidia_key  = os.getenv("NVIDIA_API_KEY")
    nvidia_base = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")

    # No fallback chain — fail fast and honest
    # If the selected model fails, return clear error so Curtis can diagnose
    nvidia_models = [model]  # Only the selected model, no silent fallback

    if nvidia_key:
        for attempt_model in nvidia_models:
            try:
                url = f"{nvidia_base}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {nvidia_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": attempt_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 4096,
                }
                r = requests.post(url, headers=headers, json=payload, timeout=(5, 15))
                r.raise_for_status()
                data = r.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                if content and content.strip():
                    if attempt_model != model:
                        print(f"[JARVIS_CHAT] Used fallback model: {attempt_model}", flush=True)
                    _record_tokens("jarvis", attempt_model, "nvidia", data)
                    return _process_content(content)
                print(f"[JARVIS_CHAT] Model {attempt_model} returned empty content", flush=True)
                return f"⚠ Model `{attempt_model}` returned empty response. Check Models page and run a benchmark, or select a different model in the Agents page."
            except Exception as e:
                err = str(e)[:120]
                print(f"[JARVIS_CHAT] {attempt_model} failed: {err}", flush=True)
                return f"⚠ Model `{attempt_model}` failed: {err}\n\nNo fallback configured. Go to Models page to run a benchmark, then select a working model in the Agents page."

    return "⚠ No NVIDIA API key configured. Cannot reach selected model."

# ==================================================
# JARVIS AUTONOMOUS EXECUTION ENGINE
# ==================================================

def _enforce_exec_naming(command: str) -> str:
    """
    If a bash command writes a .md file without a date prefix,
    rewrite the command to use the correct naming convention.
    """
    import re
    from datetime import datetime as _dt
    # Match tee, >, >> writing to a .md file
    pattern = re.compile(r'(/[\w/.-]+/)(\w[\w.-]*\.md)')
    def replace_path(m):
        dir_part = m.group(1)
        filename = m.group(2)
        if re.match(r'\d{4}-\d{2}-\d{2}_', filename):
            return m.group(0)  # already dated
        timestamp = _dt.utcnow().strftime("%Y-%m-%d_%H-%M")
        return f"{dir_part}{timestamp}_{filename}"
    # Only apply to write operations
    if any(op in command for op in [" > ", " >> ", "tee ", "cat >"]):
        return pattern.sub(replace_path, command)
    return command


def jarvis_exec_bash(command: str, timeout: int = 30) -> str:
    """Execute a bash command autonomously and return output."""
    try:
        import subprocess
        # Enforce naming convention on file write commands
        command = _enforce_exec_naming(command)
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode == 0:
            return out or "(command completed, no output)"
        return f"Exit {result.returncode}: {err or out or '(no output)'}"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Execution error: {e}"


def jarvis_read_logs(container: str, lines: int = 40) -> str:
    """Read container logs autonomously."""
    try:
        import subprocess
        result = subprocess.run(
            f"docker logs {container} --tail {lines} 2>&1",
            shell=True, capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip() or result.stderr.strip() or "(no logs)"
    except Exception as e:
        return f"Log error: {e}"


def jarvis_dispatch_agent(agent: str, instruction: str, chain_id: str = None) -> str:
    """
    Dispatch a task directly to a specialist agent via Redis.
    Returns confirmation or error.
    """
    agent_queues = {
        "systems":  "queue.agent.systems",
        "code":     "queue.agent.code",
        "research": "queue.agent.research",
        "revenue":  "queue.agent.revenue",
        "sales":    "queue.agent.sales",
        "growth":   "queue.agent.growth",
        "product":  "queue.agent.product",
        "legal":    "queue.agent.legal",
        "voice":    "queue.agent.voice",
    }

    agent_task_types = {
        "systems":  "direct_command",
        "code":     "code_task",
        "research": "offer_stack",
        "revenue":  "offer_stack",
        "sales":    "offer_stack",
        "growth":   "offer_stack",
        "product":  "offer_stack",
        "legal":    "offer_stack",
        "voice":    "chat",
    }

    queue = agent_queues.get(agent.lower())
    if not queue:
        return f"Unknown agent: {agent}. Available: {', '.join(agent_queues.keys())}"

    try:
        import uuid as _uuid
        task_id = str(_uuid.uuid4())
        if not chain_id:
            chain_id = task_id

        task_type = agent_task_types.get(agent.lower(), "offer_stack")

        # Load doctrine
        doctrine = load_doctrine() or ""

        # Auto-inject save path if instruction doesn't already contain one
        _has_path = (
            "/ai-firm/data/reports/" in instruction
            or "save to" in instruction.lower()
            or "save your" in instruction.lower()
        )
        if not _has_path and agent.lower() not in ("systems", "code", "voice"):
            import re as _re
            from datetime import datetime as _dt
            _ts = _dt.now().strftime("%Y-%m-%d_%H-%M")
            _slug = _re.sub(r'[^a-z0-9]+', '-', instruction[:40].lower()).strip('-')
            _save_path = f"/ai-firm/data/reports/{agent.lower()}/{_ts}_{_slug}.md"
            instruction = instruction + f"\n\nSave your completed report to: {_save_path}"

        envelope = {
            "agent":      agent.lower(),
            "task_type":  task_type,
            "chain_id":   chain_id,
            "payload": {
                "instruction": instruction,
                "agent":       agent.lower(),
                "chain_id":    chain_id,
                "task_type":   task_type,
                "target":      instruction[:80],
                "product":     instruction[:80],
                "message":     instruction,
            },
            "doctrine": doctrine,
        }

        # PATCH1_TELEGRAM_CHAIN_MIRROR
        r.rpush(queue, json.dumps(envelope))

        # ── TELEGRAM CHAIN MIRROR — persist telegram_chat_id for this chain ──
        # So _post_chain_synthesis can mirror the synthesis back to Telegram
        try:
            _tg_cid = TELEGRAM_BY_CHAIN.get(chain_id)
            if not _tg_cid:
                # Try to find it from active session context stored in Redis
                _tg_key = r.get(f"telegram_chat_for_session:{_current_session_id}")
                if _tg_key:
                    TELEGRAM_BY_CHAIN[chain_id] = _tg_key.decode() if isinstance(_tg_key, bytes) else _tg_key
                    print(f"[TELEGRAM_BY_CHAIN] Set chain {chain_id[:8]} → {TELEGRAM_BY_CHAIN[chain_id]}", flush=True)
        except Exception as _tbe:
            pass  # Non-fatal — mirror is best-effort

        # Post chain event so dashboard shows agent as working
        try:
            requests.post(f"{API_BASE_URL}/chains/{chain_id}/event", json={
                "event": "step_started",
                "agent": agent.lower(),
            }, timeout=2)
        except Exception:
            pass

        # Write to Jarvis memory
        _write_jarvis_memory(f"Dispatched to {agent}: {instruction[:100]}")

        return f"✓ Task dispatched to {agent} agent (queue: {queue}, chain: {chain_id[:8]}...)"
    except Exception as e:
        return f"Dispatch failed: {e}"


def jarvis_process_exec_tags(response_text: str, chain_id: str = None) -> tuple:
    """
    Parse Jarvis response for execution tags and run them.
    After execution, does a second LLM pass so Jarvis responds
    based on ACTUAL tool output — never fabricated results.
    Returns (modified_response, execution_results)

    Tags supported:
    [EXEC:bash] command [/EXEC]
    [EXEC:logs] container [/EXEC]
    [DISPATCH:agent] instruction [/DISPATCH]
    """
    results = []
    modified = response_text
    has_exec = False

    # Collect all tool outputs first
    tool_outputs = []

    # Process [EXEC:bash] tags
    exec_pattern = re.compile(r'\[EXEC:bash\](.*?)\[/EXEC\]', re.DOTALL)
    for match in exec_pattern.finditer(response_text):
        has_exec = True
        cmd = match.group(1).strip()
        output = jarvis_exec_bash(cmd)
        failed = not output.startswith("(command") and (
            output.startswith("Exit ") or
            output.startswith("Command timed out") or
            output.startswith("Execution error")
        )
        label = "FAILED" if failed else "SUCCESS"
        results.append("[bash: " + cmd[:50] + "]\n" + output)
        tool_outputs.append(f"TOOL [{label}]\nCommand: {cmd}\nOutput:\n{output}")
        modified = modified.replace(match.group(0), "```\n$ " + cmd + "\n" + output + "\n```")

    # Process [EXEC:logs] tags
    logs_pattern = re.compile(r'\[EXEC:logs\](.*?)\[/EXEC\]', re.DOTALL)
    for match in logs_pattern.finditer(response_text):
        has_exec = True
        container = match.group(1).strip()
        output = jarvis_read_logs(container)
        results.append("[logs: " + container + "]\n" + output[:500])
        tool_outputs.append(f"TOOL [SUCCESS]\nLogs: {container}\nOutput:\n{output[:500]}")
        modified = modified.replace(match.group(0), f"``` [{container} logs] {output} ```")

    # Process [DISPATCH:agent] tags
    dispatch_pattern = re.compile(r'\[DISPATCH:(\w+)\](.*?)\[/DISPATCH\]', re.DOTALL)
    for match in dispatch_pattern.finditer(response_text):
        agent = match.group(1).strip()
        instruction = match.group(2).strip()
        result = jarvis_dispatch_agent(agent, instruction, chain_id)
        results.append("[dispatch: " + agent + "]\n" + result)
        tool_outputs.append(f"TOOL [DISPATCH]\nAgent: {agent}\nResult: {result}")
        modified = modified.replace(match.group(0), "*[" + result + "]*")

    # Second LLM pass: if any EXEC tags ran, re-synthesize response from real output
    if has_exec and tool_outputs:
        try:
            tool_block = "\n\n".join(tool_outputs)
            synthesis_prompt = f"""You just executed the following tools. Here are the REAL results:

{tool_block}

LAW: If any tool shows FAILED or Exit 1+, you MUST report the failure exactly. Never invent success.
LAW: Your response must be based ONLY on the actual output above — not what you expected.

Now give Curtis your final response based on these actual results. Be direct and concise."""
            synthesized = call_llm_jarvis(synthesis_prompt)
            if synthesized and len(synthesized) > 20:
                return synthesized, results
        except Exception as _syn_err:
            print(f"[JARVIS] Synthesis pass failed: {_syn_err}", flush=True)

    return modified, results


# ==================================================
# RESULT STORAGE (in-memory; DB is source of truth)
# ==================================================

RESULTS_BY_CHAIN: Dict[str, Dict[str, str]] = {}
_current_chain_id: Optional[str] = None
TARGET_BY_CHAIN: Dict[str, str] = {}
PRODUCT_BY_CHAIN: Dict[str, str] = {}


def _result_to_text(result: dict) -> str:
    """
    Convert agent result payload into a stable text output for DB.
    Extracts actual text content from known artifact data keys.
    Falls back to json.dumps if no known key found.
    """
    data = result.get("data")
    if data is None:
        return ""
    if isinstance(data, str):
        return data

    # Known keys that contain the actual agent output text — check in priority order
    TEXT_KEYS = [
        "report",        # research, revenue, legal, product, growth, sales
        "code_output",   # code agent (Claude Code bridge output)
        "summary",       # code agent fallback summary
        "content",       # generic
        "text",          # generic
        "output",        # systems
        "synthesis",     # systems direct_command
        "strategy",      # growth, sales
        "analysis",      # legal
        "raw_output",    # legacy
        "stdout",        # bash tool
        "message",       # chat echo
    ]

    if isinstance(data, dict):
        for key in TEXT_KEYS:
            val = data.get(key)
            if val and isinstance(val, str) and len(val) > 20:
                return val
        # No known key found — dump the dict so we at least see something
        try:
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return str(data)

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
            # Resolve the actual instruction — prefer explicit instruction,
            # fall back to product (user message), then target
            resolved_instruction = (
                envelope.get("instruction") or
                envelope.get("payload", {}).get("instruction") or
                envelope.get("payload", {}).get("message") or
                product or
                target or
                ""
            )

            payload = {
                "chain_id":    chain_id,
                "target":      target,
                "product":     product,
                "instruction": resolved_instruction,
                "message":     resolved_instruction,
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
                # Use actual message as topic (truncated) instead of generic "chat"
                _topic = (msg or "").strip()[:60] or "chat"
                TARGET_BY_CHAIN[chain_id] = _topic
                PRODUCT_BY_CHAIN[chain_id] = msg or ""
                # Record session_id and telegram_chat_id for mirroring
                # PATCHA_SESS_TRACK
                _sess_id = incoming_payload.get("session_id") or envelope.get("session_id") or ""
                # Track active session + Telegram chat ID for chain mirror
                if _sess_id:
                    _tg_cid = incoming_payload.get("telegram_chat_id") or envelope.get("telegram_chat_id")
                    if _tg_cid:
                        try:
                            r.set(f"telegram_chat_for_session:{_sess_id}", str(_tg_cid), ex=86400)
                        except Exception:
                            pass
                if _sess_id:
                    SESSION_BY_CHAIN[chain_id] = _sess_id
                _tg_chat = incoming_payload.get("telegram_chat_id") or envelope.get("telegram_chat_id") or ""
                if _tg_chat:
                    TELEGRAM_BY_CHAIN[chain_id] = _tg_chat

                RESULTS_BY_CHAIN.setdefault(chain_id, {})

                # Chain started event
                global _current_chain_id
                _current_chain_id = chain_id
                chain_started(chain_id)

                # Jarvis step started/completed
                step_started(chain_id, "jarvis")

                # Handle run: prefix — execute bash directly
                msg_stripped = (msg or "").strip()
                if msg_stripped.lower().startswith("run:"):
                    cmd = msg_stripped[4:].strip()
                    try:
                        import subprocess
                        result = subprocess.run(
                            cmd, shell=True, capture_output=True, text=True, timeout=30
                        )
                        stdout = result.stdout.strip()
                        stderr = result.stderr.strip()
                        if result.returncode == 0:
                            reply = f"```\n{stdout or '(no output)'}\n```"
                        else:
                            reply = f"Command failed (exit {result.returncode}):\n```\n{stderr or stdout or '(no output)'}\n```"
                    except Exception as e:
                        reply = f"Execution error: {e}"

                elif msg_stripped.lower().startswith("logs:"):
                    target = msg_stripped[5:].strip()
                    try:
                        import subprocess
                        result = subprocess.run(
                            f"docker logs {target} --tail 50 2>&1",
                            shell=True, capture_output=True, text=True, timeout=15
                        )
                        reply = f"```\n{result.stdout.strip() or result.stderr.strip() or '(no output)'}\n```"
                    except Exception as e:
                        reply = f"Logs error: {e}"

                elif msg_stripped.lower().startswith("read:"):
                    filepath = msg_stripped[5:].strip()
                    try:
                        with open(filepath) as fh:
                            content = fh.read()
                        reply = f"```\n{content[:3000]}\n```" + ("\n*(truncated)*" if len(content) > 3000 else "")
                    except Exception as e:
                        reply = f"Cannot read file: {e}"

                else:
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
                # Telegram direct mirror — send reply back to originating Telegram chat
                _tg_chat_id = TELEGRAM_BY_CHAIN.get(chain_id, "")
                if _tg_chat_id:
                    _send_telegram_mirror(_tg_chat_id, reply)
                # Write Jarvis reply to session so Mission Control UI shows it
                _reply_sess = SESSION_BY_CHAIN.get(chain_id, "")
                if _reply_sess and not _reply_sess.startswith("telegram:"):
                    try:
                        import uuid as _uuid_r
                        _sr = requests.get(f"{API_BASE_URL}/sessions/{_reply_sess}", timeout=5)
                        if _sr.ok:
                            _sdata = _sr.json()
                            _smsgs = _sdata.get("messages", [])
                            if isinstance(_smsgs, str):
                                import json as _json_r
                                _smsgs = _json_r.loads(_smsgs)
                            _smsgs.append({
                                "id": str(_uuid_r.uuid4())[:8],
                                "role": "jarvis",
                                "content": reply,
                                "timestamp": datetime.utcnow().isoformat(),
                                "mode": "jarvis",
                            })
                            requests.put(f"{API_BASE_URL}/sessions/{_reply_sess}",
                                json={"messages": _smsgs}, timeout=5)
                            print(f"[Orchestrator] Reply written to session {_reply_sess[:8]}", flush=True)
                    except Exception as _se:
                        print(f"[Orchestrator] Session write error: {_se}", flush=True)
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
                    "doctrine": load_doctrine() or DOCTRINE_CONTENT or ""
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

            # Auto-save chain report to filesystem
            try:
                topic = TARGET_BY_CHAIN.get(chain_id, "")
                report_path = _save_chain_report(chain_id, topic, ceo, results_by_agent)
                if report_path:
                    print(f"[Orchestrator] Chain report saved: {report_path}")
                    _write_jarvis_memory(f"Chain completed: {topic}\nReport: {report_path}\nSummary: {ceo[:300]}")
            except Exception as _save_err:
                print(f"[Orchestrator] Report save error: {_save_err}")

            # POST CHAIN SYNTHESIS — present results to Curtis in chat
            try:
                _post_chain_synthesis(chain_id, results_by_agent, TARGET_BY_CHAIN.get(chain_id, ""), report_path or "")
            except Exception as _syn_err:
                print(f"[Orchestrator] Synthesis post error: {_syn_err}")

            # API telemetry: chain completed with breakdown + CEO summary
            chain_completed(chain_id, results_by_agent, ceo)
            continue

        dispatch(next_agent, task_type, payload, doctrine, chain_id)




# ==================================================
# CHAIN SYNTHESIS — Post agent results back to Curtis
# ==================================================

def _send_telegram_mirror(chat_id: str, text: str) -> None:
    """Send Jarvis reply back to Telegram chat."""
    try:
        import urllib.request as _ur, json as _j
        token = os.getenv("TELEGRAM_TOKEN", "").strip()
        if not token or not chat_id:
            return
        # Strip markdown bold markers for cleaner Telegram display
        clean = text.replace("**", "").replace("[Chain Complete]", "").strip()
        payload = _j.dumps({"chat_id": chat_id, "text": clean[:4000]}).encode()
        req = _ur.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=10) as resp:
            pass
        print(f"[Orchestrator] Telegram mirror sent to {chat_id}", flush=True)
    except Exception as _te:
        print(f"[Orchestrator] Telegram mirror failed: {_te}", flush=True)


# Track session_id per chain for Telegram mirroring
SESSION_BY_CHAIN: Dict[str, str] = {}
# Track originating Telegram chat_id per chain
TELEGRAM_BY_CHAIN: Dict[str, str] = {}


def _post_chain_synthesis(chain_id: str, results_by_agent: dict, topic: str, report_path: str) -> None:
    """
    After a chain completes, read the agent outputs and post a
    clean synthesis to the active chat session so Curtis sees results.
    Also mirrors to Telegram if the session originated from Telegram.
    """
    try:
        # Use session_id from chain if available, else get most recent session
        session_id = SESSION_BY_CHAIN.get(chain_id, "")
        if not session_id:
            sess_r = requests.get(f"{API_BASE_URL}/sessions", timeout=5)
            if not sess_r.ok:
                return
            sessions = sess_r.json()
            if not sessions:
                return
            session_id = sessions[0].get("id")
        if not session_id:
            return

        # Build synthesis prompt from real agent outputs
        agent_outputs = ""
        for agent, output in results_by_agent.items():
            if output and output.strip():
                # Parse JSON report if wrapped
                try:
                    parsed = json.loads(output)
                    if isinstance(parsed, dict):
                        output = parsed.get("report") or parsed.get("summary") or parsed.get("synthesis") or output
                except Exception:
                    pass
                agent_outputs += f"\n### {agent.upper()}\n{str(output)[:600]}\n"

        if not agent_outputs.strip():
            return

        synthesis_prompt = f"""The following agents just completed work on this task:
TASK: {topic}

AGENT OUTPUTS:
{agent_outputs}

Your job: synthesize these outputs into a crisp executive briefing for Curtis.
Format:
- 2-3 sentence summary of what was accomplished
- Key findings or deliverables from each agent (1 line each, skip agents that asked for more info)
- 1-2 recommended next actions

Be direct. No theater. If agents asked for clarification instead of executing, flag that clearly.
Report path: {report_path}"""

        synthesis = call_llm_jarvis(synthesis_prompt)
        if not synthesis or len(synthesis) < 20:
            return

        # Post to session
        sess_data = requests.get(f"{API_BASE_URL}/sessions/{session_id}", timeout=5)
        if not sess_data.ok:
            return
        messages = sess_data.json().get("messages", [])

        import uuid as _u
        messages.append({
            "id": str(_u.uuid4())[:8],
            "role": "jarvis",
            "content": f"**[Chain Complete]** {synthesis}",
            "timestamp": datetime.utcnow().isoformat(),
            "mode": "jarvis",
        })

        requests.put(f"{API_BASE_URL}/sessions/{session_id}",
            json={"messages": messages}, timeout=5)
        print(f"[Orchestrator] Chain synthesis posted to session {session_id[:8]}")
        # Mirror to Telegram if chain originated from Telegram
        _tg_mirror_id = TELEGRAM_BY_CHAIN.get(chain_id, "")
        if _tg_mirror_id:
            _send_telegram_mirror(_tg_mirror_id, synthesis)

    except Exception as e:
        print(f"[Orchestrator] _post_chain_synthesis error: {e}")


# ==================================================
# PROACTIVE JARVIS MESSAGING
# Sends status updates to active chat sessions autonomously
# ==================================================
import threading as _threading

# Global flag to prevent duplicate proactive threads
_proactive_thread_started = False

# PATCHB_AUTONOMY_ENGINE
def _run_morning_briefing(session_id: str) -> None:
    """Generate and deliver morning intelligence briefing via Claude Code bridge."""
    import subprocess as _sbp
    try:
        print("[AUTONOMY] Running morning briefing...", flush=True)
        date_str = __import__("datetime").datetime.now().strftime("%A, %B %d, %Y")
        ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d_%H-%M")
        save_path = f"/srv/silentempire/ai-firm/data/reports/research/{ts}_morning-briefing.md"

        briefing_prompt = f"""Generate the morning intelligence briefing for Curtis Proske, Founder of Silent Empire AI.
Date: {date_str}

Execute these steps:
1. Check recent reports: ls /srv/silentempire/ai-firm/data/reports/research/ 2>/dev/null | tail -5
2. Read Jarvis memory: cat /srv/silentempire/ai-firm/data/memory/jarvis/core.md 2>/dev/null | tail -30
3. Search market: python3 /srv/silentempire/ai-firm/tools/ddg_search.py "irrevocable trust asset protection 2026"
4. Check chain reports: ls -t /srv/silentempire/ai-firm/data/reports/chains/*.md 2>/dev/null | head -3

Write this briefing then save to {save_path}:

# Morning Briefing — {date_str}

## Priority Actions Today
[3 specific, numbered actions Curtis should do TODAY — each with why it matters now]

## Agent Activity (Last 24h)
[What agents produced — specific outputs, quality scores, files written]

## Market Intelligence
[2-3 findings from search — specific, not generic]

## Revenue Status
[Honest assessment vs $1K/day target + ONE action to move revenue today]

## Recommended Dispatches
[2-3 specific agent tasks ready to run — agent name + exact instruction]

Tight. Actionable. 90-second read. No fluff.
After saving, output ONLY the briefing text for Telegram delivery."""

        resp = requests.post(
            "http://172.18.0.1:9999/run",
            json={{"prompt": briefing_prompt, "work_dir": "/srv/silentempire", "timeout": 180}},
            timeout=200
        )
        data = resp.json()
        if data.get("success") and data.get("output"):
            briefing_text = data["output"].strip()
            _send_telegram_mirror(briefing_text, None)
            # Write to session
            try:
                import uuid as _u2
                msg = {{"id": str(_u2.uuid4())[:8], "role": "jarvis",
                        "content": f"**[Morning Briefing]**\n{{briefing_text[:3000]}}",
                        "timestamp": __import__("datetime").datetime.utcnow().isoformat(), "mode": "jarvis"}}
                sd = requests.get(f"{{API_BASE_URL}}/sessions/{{session_id}}", timeout=5)
                if sd.ok:
                    ex = sd.json(); msgs = ex.get("messages", []); msgs.append(msg)
                    requests.put(f"{{API_BASE_URL}}/sessions/{{session_id}}", json={{"messages": msgs}}, timeout=5)
            except Exception:
                pass
            print("[AUTONOMY] Morning briefing delivered.", flush=True)
        else:
            print(f"[AUTONOMY] Briefing failed: {{data.get('output','?')[:200]}}", flush=True)
    except Exception as _e:
        print(f"[AUTONOMY] Morning briefing error: {{_e}}", flush=True)


def _run_opportunity_scan(session_id: str) -> None:
    """Autonomous opportunity scan — identifies revenue opportunities, runs 2x/day."""
    try:
        print("[AUTONOMY] Running opportunity scan...", flush=True)
        ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d_%H-%M")
        save_path = f"/srv/silentempire/ai-firm/data/reports/research/{{ts}}_opportunity-scan.md"

        scan_prompt = f"""You are Jarvis's autonomous intelligence module for Silent Empire AI.
Run an opportunity scan. Execute all steps:

1. python3 /srv/silentempire/ai-firm/tools/ddg_search.py "asset protection trust market demand 2026"
2. python3 /srv/silentempire/ai-firm/tools/ddg_search.py "irrevocable trust divorce protection competitors pricing"
3. python3 /srv/silentempire/ai-firm/tools/ddg_search.py "high income men asset protection lawsuits divorce"
4. ls /srv/silentempire/ai-firm/data/reports/research/ | tail -5

Save a focused opportunity report to: {save_path}

Report format:
# Opportunity Scan — {ts}
## Top 3 Opportunities (act within 48 hours)
[Each: what it is, why now, estimated revenue impact, exact agent + instruction needed]
## Content Gaps to Fill This Week
[Specific content the market searches for that we don't have — each as a title]
## Competitive Weaknesses to Exploit
[Specific gaps in competitor positioning Silent Vault can own]

After saving, output ONLY a 3-bullet summary (under 200 chars/bullet) for Telegram."""

        resp = requests.post(
            "http://172.18.0.1:9999/run",
            json={{"prompt": scan_prompt, "work_dir": "/srv/silentempire", "timeout": 180}},
            timeout=200
        )
        data = resp.json()
        if data.get("success") and data.get("output"):
            summary = data["output"].strip()
            msg_text = f"🔍 Opportunity Scan\n\n{{summary[:1500]}}"
            _send_telegram_mirror(msg_text, None)
            try:
                import uuid as _u3
                msg = {{"id": str(_u3.uuid4())[:8], "role": "jarvis",
                        "content": msg_text,
                        "timestamp": __import__("datetime").datetime.utcnow().isoformat(), "mode": "jarvis"}}
                sd = requests.get(f"{{API_BASE_URL}}/sessions/{{session_id}}", timeout=5)
                if sd.ok:
                    ex = sd.json(); msgs = ex.get("messages", []); msgs.append(msg)
                    requests.put(f"{{API_BASE_URL}}/sessions/{{session_id}}", json={{"messages": msgs}}, timeout=5)
            except Exception:
                pass
            print("[AUTONOMY] Opportunity scan complete.", flush=True)
        else:
            print(f"[AUTONOMY] Scan failed: {{data.get('output','?')[:200]}}", flush=True)
    except Exception as _e:
        print(f"[AUTONOMY] Opportunity scan error: {{_e}}", flush=True)


def _jarvis_proactive_loop():
    """Background thread: morning briefing, opportunity scan, proactive updates — elite autonomy."""
    global _proactive_thread_started
    import time as _time
    _time.sleep(120)  # Wait 2 min after startup before first action

    # Interval tracking
    _last_status      = 0
    _last_briefing    = 0
    _last_opp_scan    = 0
    STATUS_INTERVAL   = 7200   # 2 hours
    BRIEFING_INTERVAL = 21600  # 6 hours
    OPP_SCAN_INTERVAL = 28800  # 8 hours

    print("[AUTONOMY] Heartbeat interval set to 1800 seconds", flush=True)

    while True:
        try:
            _time.sleep(1800)  # Check every 30 minutes
            _now = _time.time()

            # Get active session for all autonomy functions
            _active_session = ""
            try:
                _sr = requests.get(f"{API_BASE_URL}/sessions", timeout=5)
                if _sr.ok:
                    _sessions = _sr.json()
                    if _sessions:
                        _active_session = _sessions[0].get("id", "")
            except Exception:
                pass

            # Morning briefing (every 6 hours)
            if _active_session and (_now - _last_briefing) >= BRIEFING_INTERVAL:
                _run_morning_briefing(_active_session)
                _last_briefing = _now

            # Opportunity scan (every 8 hours)
            if _active_session and (_now - _last_opp_scan) >= OPP_SCAN_INTERVAL:
                _run_opportunity_scan(_active_session)
                _last_opp_scan = _now

            # Standard proactive status update (every 2 hours)
            if (_now - _last_status) >= STATUS_INTERVAL:
                _send_proactive_update()
                _last_status = _now

        except Exception as _pe:
            print(f"[PROACTIVE] Error: {_pe}")

def _send_proactive_update():
    """Generate and post a proactive status update to the most recent chat session."""
    try:
        # Get most recent active session
        sess_r = requests.get(f"{API_BASE_URL}/sessions", timeout=5)
        if not sess_r.ok:
            return
        sessions = sess_r.json()
        if not sessions:
            return
        # Use most recently updated session
        session = sessions[0]
        session_id = session.get("id")
        if not session_id:
            return

        # ── Dedup: skip if we already sent a proactive about this sprint state ──
        try:
            import hashlib as _hashlib
            # Build a fingerprint from the ClickUp sprint task IDs that are in To Do
            # so we don't repeat the same pitch more than once per 6 hours
            dedup_key = "jarvis:proactive:last_sprint_hash"
            ttl_seconds = 6 * 3600  # 6 hours

            import subprocess as _sp2
            _sprint_raw = _sp2.run(
                ["python3", "/ai-firm/tools/clickup_cli.py", "list-tasks", "901710993025"],
                capture_output=True, text=True, timeout=15
            ).stdout or ""
            _fingerprint = _hashlib.md5(_sprint_raw.encode()).hexdigest()[:12]

            _redis_check = _sp2.run(
                ["docker", "exec", "app-redis-1", "redis-cli", "GET", dedup_key],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()

            if _redis_check == _fingerprint:
                print(f"[PROACTIVE] Sprint state unchanged (hash={_fingerprint}), skipping duplicate update")
                return

            # Store the fingerprint with TTL
            _sp2.run(
                ["docker", "exec", "app-redis-1", "redis-cli", "SET", dedup_key, _fingerprint, "EX", str(ttl_seconds)],
                capture_output=True, timeout=5
            )
            print(f"[PROACTIVE] New sprint state (hash={_fingerprint}), proceeding with update")
        except Exception as _dedup_err:
            print(f"[PROACTIVE] Dedup check failed (non-fatal): {_dedup_err}")

        # Build a proactive status message
        live = _fetch_live_data()
        # Gather real context before generating update
        clickup_context = ""
        try:
            import subprocess as _sp
            cu = _sp.run(
                ["python3", "/ai-firm/tools/clickup_cli.py", "list-tasks", "901710993025"],
                capture_output=True, text=True, timeout=10
            )
            if cu.returncode == 0 and cu.stdout.strip():
                clickup_context = f"Current Sprint tasks:\n{cu.stdout.strip()[:800]}"
        except Exception:
            pass

        # Check for new agent reports in last 2 hours
        new_files_context = ""
        try:
            import subprocess as _sp
            nf = _sp.run(
                ["find", "/ai-firm/data/reports", "-name", "*.md",
                 "-newer", "/ai-firm/data/memory/jarvis/SESSION-STATE.md",
                 "-not", "-name", ".gitkeep"],
                capture_output=True, text=True, timeout=5
            )
            if nf.stdout.strip():
                new_files_context = f"New agent reports since last check:\n{nf.stdout.strip()[:400]}"
        except Exception:
            pass

        prompt = f"""You are Jarvis, autonomous COO of Silent Empire AI.
You are sending a proactive update to Curtis (Founder).

Context available:
{clickup_context or "No ClickUp data available."}
{new_files_context or "No new agent reports."}

LIVE DATA: {_fetch_live_data()[:500]}

Generate a SHORT (3-5 sentences) proactive update that:
1. Reports ONE specific thing that actually happened or needs attention
2. States what you are doing about it or recommend as next action
3. Is concrete and actionable — not generic status narration

Do NOT say "all agents are idle" unless you have something specific to add.
Do NOT repeat the same update as last time.
If nothing notable happened, ask Curtis ONE strategic question about the trust business.
Never start with "Status Update". Be conversational and direct.
Based on this live data:
{live}

Report on:
- Any agents that are working
- Token usage highlights
- Any notable activity
- A recommended next action for the Founder

Be direct and concise. No headers. No bullet points. Just a natural status update as if you are checking in."""

        reply = call_llm_jarvis(prompt)
        if not reply or len(reply) < 20:
            return

        # Post to the session as a Jarvis message
        session_data = requests.get(f"{API_BASE_URL}/sessions/{session_id}", timeout=5)
        if not session_data.ok:
            return
        existing = session_data.json()
        messages = existing.get("messages", [])

        import uuid as _uuid2
        new_msg = {
            "id": str(_uuid2.uuid4())[:8],
            "role": "jarvis",
            "content": f"**[Status Update]** {reply}",
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "mode": "jarvis",
        }
        messages.append(new_msg)

        requests.put(f"{API_BASE_URL}/sessions/{session_id}",
            json={"messages": messages}, timeout=5)
        print(f"[PROACTIVE] Status update sent to session {session_id[:8]}")

    except Exception as e:
        print(f"[PROACTIVE] Send error: {e}")

# PATCH_CLICKUP_OS_THREAD
# Start proactive thread
_proactive_thread = _threading.Thread(target=_jarvis_proactive_loop, daemon=True, name="jarvis-proactive")
_proactive_thread.start()
print("[Proactive] Thread started.", flush=True)
print("[PROACTIVE] Proactive messaging thread started (updates every 2 hours)")

# ── ClickUp Business OS Scanner ───────────────────────────────────────────
# Uses Redis lock to prevent duplicate threads across restarts
# PATCH3_DEDUP_THREAD
_CLICKUP_LOCK_KEY = "clickup_os:scanner_running"
try:
    import importlib.util as _ilu
    import redis as _redis_check

    # Check if scanner is already running (from a previous instance)
    _rcheck = _redis_check.from_url(
        os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
        decode_responses=True
    )
    # Use a short TTL — if process dies, lock expires and scanner restarts cleanly
    _scanner_lock = _rcheck.set(_CLICKUP_LOCK_KEY, "1", ex=120, nx=True)

    if _scanner_lock:
        _cu_spec = _ilu.spec_from_file_location(
            "clickup_scanner",
            "/app/orchestrator/clickup_scanner.py"
        )
        _cu_mod = _ilu.module_from_spec(_cu_spec)
        _cu_spec.loader.exec_module(_cu_mod)

        def _clickup_loop_with_lock():
            """Renew Redis lock while running, release on exit."""
            try:
                import redis as _r2
                _rc = _r2.from_url(
                    os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
                    decode_responses=True
                )
                while True:
                    _rc.expire(_CLICKUP_LOCK_KEY, 120)  # Renew every iteration
                    import time as _t2
                    _t2.sleep(60)
            except Exception:
                pass

        _lock_renew = _threading.Thread(target=_clickup_loop_with_lock, daemon=True, name="clickup-lock-renew")
        _lock_renew.start()

        _clickup_thread = _threading.Thread(
            target=_cu_mod.clickup_scan_loop,
            daemon=True,
            name="clickup-business-os"
        )
        _clickup_thread.start()
        print("[CLICKUP_OS] Business OS scanner thread started.", flush=True)
    else:
        print("[CLICKUP_OS] Scanner already running in another instance — skipping.", flush=True)
except Exception as _cu_err:
    print(f"[CLICKUP_OS] Failed to start scanner: {_cu_err}", flush=True)


if __name__ == "__main__":
    import threading
    from orchestrator.heartbeat import hybrid_autonomy_loop

    # Start controlled hybrid autonomy in background
    threading.Thread(
        target=hybrid_autonomy_loop,
        daemon=True
    ).start()

    run()
