#!/usr/bin/env python3
"""
Silent Empire AI — ClickUp Business OS Scanner
================================================
Scans ClickUp for changes, detects Curtis's comments,
dispatches agents, posts completion results, syncs Jarvis memory.

Runs as a background thread inside jarvis-orchestrator.
Interval controlled by autonomy_config.json.

Architecture:
  1. Scan all active lists for tasks with new comments from Curtis
  2. Read full task context (description, all custom fields, subtasks recursive)
  3. Determine prerequisite status — don't dispatch if blockers exist
  4. Dispatch appropriate agent(s) based on task type + Curtis's direction
  5. Post structured completion comment back to ClickUp task
  6. Update task custom fields (Action Items, Deliverable)
  7. Sync pivots/direction changes to Jarvis + agent memory
  8. Unlock dependent tasks when prerequisites complete
"""

import json
import os
import re
import sys
import time
import uuid
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH  = Path("/ai-firm/config/autonomy_config.json")
BUSINESS_PATH = Path("/ai-firm/config/business.json")
MEMORY_BASE  = Path("/ai-firm/data/memory")
REPORTS_BASE = Path("/ai-firm/data/reports")
TOOLS_DIR    = Path("/ai-firm/tools")

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
BRIDGE_URL   = "http://172.18.0.1:9999"

# ClickUp API
CLICKUP_API = "https://api.clickup.com/api/v2"

# Custom field IDs (discovered from live workspace)
FIELD_ACTION_ITEMS   = "7d0b9482-9e4f-4efc-8c44-0e7417c1af07"
FIELD_DELIVERABLE    = "156680c8-10ae-47d8-99cd-aa438ec02d38"
FIELD_FILES          = "09a28a4e-4a98-4b37-8953-ed45e6592403"
FIELD_PRIORITY_ORDER = "e2a68874-658f-4583-8ce4-bf7ecc322f0f"

# Founder identity loaded from business.json — never hardcoded
# PATCH_NO_HARDCODED_NAMES
def _get_founder_identity() -> dict:
    """Load founder identity from business.json. White-label safe."""
    try:
        biz = json.loads(Path("/ai-firm/config/business.json").read_text())
        company = biz.get("company", {})
        return {
            "name":    company.get("founder_name", ""),
            "email":   company.get("founder_email", ""),
            "user_id": company.get("founder_clickup_user_id", 0),
        }
    except Exception:
        return {"name": "", "email": "", "user_id": 0}

def _get_bot_prefixes() -> list:
    """Load bot comment prefixes from business.json."""
    try:
        biz = json.loads(Path("/ai-firm/config/business.json").read_text())
        return biz.get("clickup", {}).get("bot_comment_prefixes", [])
    except Exception:
        return ["🤖", "✅ ", "⏳ ", "[Chain", "━━━"]

# PATCH2_REDIS_STATE
# State tracking — Redis-backed so it survives container restarts
# Format: Redis key "clickup_os:processed:{task_id}" → last_processed_timestamp
_processed_state: dict = {}  # in-memory cache

def _state_get(task_id: str) -> int:
    """Get last processed timestamp for a task (Redis-backed)."""
    # Check in-memory cache first
    if task_id in _processed_state:
        return _processed_state[task_id]
    # Check Redis
    try:
        import redis as _redis
        _r = _redis.from_url(os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"), decode_responses=True)
        val = _r.get(f"clickup_os:processed:{task_id}")
        if val:
            ts = int(val)
            _processed_state[task_id] = ts
            return ts
    except Exception:
        pass
    return 0

def _state_set(task_id: str, timestamp: int) -> None:
    """Persist processed timestamp to Redis + in-memory cache."""
    _processed_state[task_id] = timestamp
    try:
        import redis as _redis
        _r = _redis.from_url(os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"), decode_responses=True)
        # Expire after 30 days — old tasks don't need tracking forever
        _r.setex(f"clickup_os:processed:{task_id}", 2592000, str(timestamp))
    except Exception as e:
        pass  # In-memory fallback is fine

# ── Config loader ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {"clickup": {"scan_interval_minutes": 10, "enabled": True}}

def get_clickup_token() -> str:
    """Load ClickUp token from env or .env files."""
    t = os.environ.get("CLICKUP_API_TOKEN") or os.environ.get("CLICKUP_TOKEN")
    if t:
        return t
    for env_path in ["/srv/silentempire/ai-firm/.env", "/srv/silentempire/app/.env"]:
        try:
            for line in open(env_path):
                line = line.strip()
                if line.startswith("CLICKUP_TOKEN=") or line.startswith("CLICKUP_API_TOKEN="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return ""

# ── ClickUp API client ────────────────────────────────────────────────────────

def cu_get(endpoint: str, params: dict = None) -> dict:
    """ClickUp GET request."""
    token = get_clickup_token()
    url = f"{CLICKUP_API}{endpoint}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[CLICKUP] GET {endpoint} failed: {e}", flush=True)
        return {}

def cu_post(endpoint: str, data: dict) -> dict:
    """ClickUp POST request."""
    token = get_clickup_token()
    url = f"{CLICKUP_API}{endpoint}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[CLICKUP] POST {endpoint} failed: {e}", flush=True)
        return {}

def cu_put(endpoint: str, data: dict) -> dict:
    """ClickUp PUT request."""
    token = get_clickup_token()
    url = f"{CLICKUP_API}{endpoint}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        resp = requests.put(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[CLICKUP] PUT {endpoint} failed: {e}", flush=True)
        return {}

# ── Task reader with recursive subtask drill-down ────────────────────────────

def get_task_full(task_id: str, depth: int = 0, max_depth: int = 7) -> dict:
    """
    Get full task detail including all custom fields.
    Dynamically reads ALL custom fields — no hardcoding.
    """
    data = cu_get(f"/task/{task_id}", {
        "include_subtasks": "true",
        "custom_task_ids": "false",
    })
    if not data:
        return {}

    # Parse all custom fields dynamically
    custom_fields = {}
    for cf in data.get("custom_fields", []):
        name  = cf.get("name", "unknown")
        value = cf.get("value")
        ftype = cf.get("type", "text")
        fid   = cf.get("id", "")
        custom_fields[name] = {
            "id":    fid,
            "type":  ftype,
            "value": value,
        }

    task = {
        "id":            data.get("id", task_id),
        "name":          data.get("name", ""),
        "description":   data.get("description", ""),
        "status":        data.get("status", {}).get("status", "unknown"),
        "priority":      (data.get("priority") or {}).get("priority", "none"),
        "due_date":      data.get("due_date"),
        "url":           data.get("url", ""),
        "custom_fields": custom_fields,
        "tags":          [t.get("name") for t in data.get("tags", [])],
        "assignees":     [a.get("username") for a in data.get("assignees", [])],
        "depth":         depth,
        "subtasks":      [],
    }

    # Recursive subtask drill-down up to max_depth (7 levels)
    if depth < max_depth:
        for st in data.get("subtasks", []):
            st_id = st.get("id")
            if st_id:
                subtask = get_task_full(st_id, depth + 1, max_depth)
                if subtask:
                    task["subtasks"].append(subtask)

    return task


def get_task_comments(task_id: str) -> list:
    """Get all comments on a task."""
    data = cu_get(f"/task/{task_id}/comment")
    return data.get("comments", [])


def get_list_tasks(list_id: str) -> list:
    """Get all tasks in a list (not recursive — just top level)."""
    data = cu_get(f"/list/{list_id}/task", {"archived": "false", "subtasks": "false"})
    return data.get("tasks", [])


def post_comment(task_id: str, text: str) -> dict:
    """Post a comment to a task."""
    return cu_post(f"/task/{task_id}/comment", {"comment_text": text})


def update_custom_field(task_id: str, field_id: str, value) -> dict:
    """Update a custom field value on a task."""
    return cu_post(f"/task/{task_id}/field/{field_id}", {"value": value})


def update_task_status(task_id: str, status: str) -> dict:
    """Update task status."""
    return cu_put(f"/task/{task_id}", {"status": status})

# ── Lists to scan ─────────────────────────────────────────────────────────────

# All lists Jarvis monitors. Add/remove as workspace evolves.
# Loaded from config if present, otherwise these defaults.
DEFAULT_SCAN_LISTS = {
    # COMMAND CENTER — primary operational lists
    "Current Sprint":           "901710993025",
    "Sprint Backlog":           "901710993026",
    "Active Blockers":          "901710993027",
    "10K Roadmap":              "901710993021",
    "Competitive Intelligence": "901710993022",
    "Channel Strategy":         "901710993023",
    "GTM Playbooks":            "901710993024",
    "Approvals Queue":          "901710993041",
    "Jarvis DMs":               "901710993042",
    "Research Vault":           "901710993034",
    "Lessons Learned":          "901710993031",
    # Silent Vault Launch
    "Research & Strategy":      "901711321852",
    "Content & Assets":         "901711321853",
    "Execution & Sales":        "901711321854",
}

def get_scan_lists(cfg: dict) -> dict:
    """Get lists to scan from config or defaults. Respects excluded_folders + excluded_lists."""
    cu_cfg = cfg.get("clickup", {})
    custom = cu_cfg.get("scan_lists", {})
    base = custom if custom else DEFAULT_SCAN_LISTS

    # Load exclusions from business.json (no hardcoding)
    excluded_folders = set(str(x) for x in cu_cfg.get("excluded_folders", []))
    excluded_lists   = set(str(x) for x in cu_cfg.get("excluded_lists", []))

    if not excluded_folders and not excluded_lists:
        return base

    # Filter out excluded lists. For folder exclusion, query the list's folder_id.
    filtered = {}
    for name, list_id in base.items():
        list_id_str = str(list_id)
        if list_id_str in excluded_lists:
            print(f"[CLICKUP_OS] Skipping excluded list: {name} ({list_id_str})", flush=True)
            continue
        if excluded_folders:
            try:
                list_data = cu_get(f"/list/{list_id_str}", {})
                folder_id = str((list_data.get("folder") or {}).get("id", ""))
                space_id  = str((list_data.get("space") or {}).get("id", ""))
                if folder_id in excluded_folders or space_id in excluded_folders:
                    print(f"[CLICKUP_OS] Skipping list {name} — folder/space {folder_id or space_id} is excluded", flush=True)
                    continue
            except Exception as _exc:
                pass  # Non-fatal — include list if lookup fails
        filtered[name] = list_id
    return filtered

# ── Change detection ──────────────────────────────────────────────────────────

def is_curtis_comment(comment: dict) -> bool:
    """
    Check if a comment is a real human direction from the founder.
    Uses TWO checks:
    1. User ID matches founder (loaded from business.json)
    2. Comment text does NOT start with a bot prefix

    This prevents the recursive loop where Jarvis comments as the founder's
    account and the scanner re-processes them as new instructions.
    """
    # Load founder identity dynamically
    founder = _get_founder_identity()
    bot_prefixes = _get_bot_prefixes()

    user = comment.get("user", {})
    user_id  = user.get("id", 0)
    username = user.get("username", "")
    email    = user.get("email", "")

    # Check if this is the founder's account
    is_founder = (
        (founder["user_id"] and user_id == founder["user_id"]) or
        (founder["name"]  and username == founder["name"]) or
        (founder["email"] and email    == founder["email"])
    )

    if not is_founder:
        return False

    # Even if it's the founder's account, reject bot-generated comments
    # (Jarvis posts via the same API token, so same user ID)
    comment_text = comment.get("comment_text", "").strip()
    for prefix in bot_prefixes:
        if comment_text.startswith(prefix):
            return False

    # Additional bot pattern check — Jarvis acknowledgment format
    bot_patterns = [
        "Dispatching:", "Agent Direction:", "Chain tracking active",
        "AGENT COMPLETE", "Task dispatched", "chain_id=",
        "Report saved", "Google Drive", "COMPLETION_SUMMARY",
    ]
    for pattern in bot_patterns:
        if pattern in comment_text:
            return False

    return True


def get_new_curtis_comments(task_id: str) -> list:
    """
    Get Curtis's comments on a task that haven't been processed yet.
    Uses Redis-backed timestamp tracking — survives container restarts.
    """
    comments = get_task_comments(task_id)
    last_processed = _state_get(task_id)
    new_comments = []

    for c in comments:
        if not is_curtis_comment(c):
            continue
        ts = int(c.get("date", 0))
        if ts > last_processed:
            new_comments.append(c)

    return new_comments


def mark_task_processed(task_id: str, comments: list) -> None:
    """Mark task as processed up to the latest comment timestamp (Redis-backed)."""
    if not comments:
        return
    latest_ts = max(int(c.get("date", 0)) for c in comments)
    _state_set(task_id, latest_ts)

# ── Action classification ─────────────────────────────────────────────────────

# Map task name prefixes/keywords to agent assignments
TASK_AGENT_MAP = [
    (["RESEARCH:", "research", "competitive", "analysis", "market", "intel"],    "research"),
    (["MARKETING:", "content", "hook", "copy", "email", "social", "script"],     "sales"),
    (["SALES:", "conversion", "funnel", "lead magnet", "proposal", "close"],      "sales"),
    (["REVENUE:", "pricing", "offer", "monetization", "financial"],               "revenue"),
    (["GROWTH:", "traffic", "acquisition", "channel", "paid", "organic"],         "growth"),
    (["LEGAL:", "compliance", "disclaimer", "contract", "risk", "regulation"],    "legal"),
    (["PRODUCT:", "roadmap", "feature", "onboarding", "delivery", "template"],    "product"),
    (["STRATEGY:", "positioning", "architecture", "scale", "GTM"],                "research"),
    (["TECHNOLOGY:", "AUTOMATION:", "code", "build", "deploy", "script", "API"],  "code"),
    (["OPERATIONS:", "OPS", "SOP", "infrastructure", "system"],                   "systems"),
]

def classify_task_agent(task_name: str, task_desc: str) -> str:
    """Determine which agent should handle this task."""
    text = (task_name + " " + task_desc).lower()
    for keywords, agent in TASK_AGENT_MAP:
        for kw in keywords:
            if kw.lower() in text:
                return agent
    return "research"  # default fallback


def extract_direction(comment_text: str) -> dict:
    """
    Parse Curtis's comment to extract:
    - instruction: what to do
    - is_pivot: does this change previous direction?
    - is_approval: is this approving previous work?
    - is_rejection: is this requesting revision?
    - memory_update: content to add to agent/Jarvis memory
    """
    text = comment_text.strip()
    text_lower = text.lower()

    is_pivot = any(w in text_lower for w in [
        "pivot", "change direction", "new direction", "instead", "actually",
        "forget", "scratch that", "different", "revised", "update the strategy"
    ])
    is_approval = any(w in text_lower for w in [
        "approved", "looks good", "great", "perfect", "proceed", "go ahead",
        "do it", "execute", "ship it", "yes", "confirmed", "publish"
    ])
    is_rejection = any(w in text_lower for w in [
        "redo", "revise", "not right", "wrong", "fix", "change this",
        "not what i wanted", "try again", "rework", "needs work"
    ])

    return {
        "instruction":    text,
        "is_pivot":       is_pivot,
        "is_approval":    is_approval,
        "is_rejection":   is_rejection,
        "memory_update":  text if (is_pivot or is_approval) else "",
    }

# ── Prerequisite checker ──────────────────────────────────────────────────────

def check_prerequisites_met(task: dict) -> tuple[bool, str]:
    """
    Check if a task's prerequisites are met before dispatching agents.
    Returns (met, reason).

    Rules:
    - Tasks with Priority Order 1 can always proceed
    - Tasks with Priority Order 2+ need Priority Order 1 tasks in same list to be complete
    - Tasks tagged [BLOCKED] cannot proceed
    - Subtasks can proceed if parent is in progress or complete
    """
    task_name = task.get("name", "")
    cf = task.get("custom_fields", {})
    priority_order = cf.get("Priority Order", {}).get("value")

    # Blocked tag check
    if any("blocked" in str(t).lower() for t in task.get("tags", [])):
        return False, "Task is tagged as blocked"

    # Priority order 1 = foundational, always can proceed
    if priority_order == 1 or priority_order == "1":
        return True, "Priority 1 task — foundational, proceed"

    # For now, allow all tasks to proceed — will tighten as workspace matures
    # Future: check that lower priority_order tasks in same list are complete
    return True, f"Priority {priority_order} — proceeding"

# ── Agent dispatch ────────────────────────────────────────────────────────────

def build_agent_instruction(task: dict, direction: dict, agent: str) -> str:
    """Build a complete, context-rich instruction for the agent."""
    cf = task.get("custom_fields", {})
    existing_deliverable = cf.get("Deliverable", {}).get("value", "") or ""
    existing_action_items = cf.get("Action Items", {}).get("value", "") or ""

    # Format subtask context
    subtask_context = ""
    if task.get("subtasks"):
        subtask_lines = []
        for st in task["subtasks"][:10]:
            subtask_lines.append(f"  - [{st.get('status','?')}] {st.get('name','')}")
        subtask_context = "\nSubtasks:\n" + "\n".join(subtask_lines)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    slug = re.sub(r'[^a-z0-9]+', '-', task.get('name', 'task')[:40].lower()).strip('-')
    save_path = f"/srv/silentempire/ai-firm/data/reports/{agent}/{ts}_{slug}.md"

    instruction = f"""You are the {agent.title()} Agent for Silent Empire AI.

CLICKUP TASK: {task.get('name', '')}
Task ID: {task.get('id', '')}
Task URL: {task.get('url', '')}
Status: {task.get('status', '')}
Priority: {task.get('priority', '')}

TASK DESCRIPTION:
{task.get('description', '(none)')}

CURTIS'S DIRECTION:
{direction.get('instruction', '')}

EXISTING DELIVERABLE: {existing_deliverable or '(none yet)'}
EXISTING ACTION ITEMS: {existing_action_items or '(none yet)'}
{subtask_context}

YOUR MISSION:
Produce the deliverable for this task based on Curtis's direction above.
This is real business work — Silent Vault Trust System, asset protection for high-income men.

REQUIRED OUTPUT FORMAT:
1. Executive summary (3-5 sentences)
2. Full deliverable content (complete, not a template)
3. Specific next actions (numbered list)
4. Any risks or dependencies to flag

SAVE YOUR REPORT TO: {save_path}

After completing, return a structured summary in this format:
COMPLETION_SUMMARY: [2-3 sentence summary of what was produced]
DELIVERABLE_LINK: {save_path}
NEXT_ACTIONS: [bullet list of 3-5 specific next steps]
MEMORY_NOTE: [one sentence of key learning or pivot to remember]"""

    # Add revision context if this is a rejection/revision request
    if direction.get("is_rejection"):
        instruction += f"\n\nREVISION REQUEST: Curtis has asked for revisions. Previous work needs to be improved. Focus specifically on: {direction['instruction']}"

    return instruction


# PATCH2A_CHAIN_LOCK
def dispatch_to_agent(agent: str, instruction: str, task_id: str) -> str:
    """Dispatch instruction to agent via Redis queue. Includes chain lock + circuit breaker."""
    try:
        import redis as _redis
        _r = _redis.from_url(os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"), decode_responses=True)

        # ── CHAIN LOCK — prevent duplicate dispatches for same task ──────────
        lock_key = f"chain_lock:{task_id}"
        lock_ttl = 1800  # 30 minutes
        try:
            cfg = json.loads(Path("/ai-firm/config/autonomy_config.json").read_text())
            lock_ttl = cfg.get("clickup", {}).get("chain_lock_ttl_seconds", 1800)
        except Exception:
            pass

        # SET NX (only set if not exists) — atomic lock
        acquired = _r.set(lock_key, "1", ex=lock_ttl, nx=True)
        if not acquired:
            print(f"[CLICKUP_OS] Chain lock active for task {task_id} — skipping duplicate dispatch", flush=True)
            return ""

        # ── CIRCUIT BREAKER — halt if queues are backed up ───────────────────
        circuit_limit = 20
        try:
            circuit_limit = cfg.get("budget", {}).get("circuit_breaker_queue_depth", 20)
        except Exception:
            pass

        agent_queues_to_check = [
            "queue.agent.research", "queue.agent.sales", "queue.agent.revenue",
            "queue.agent.growth", "queue.agent.product", "queue.agent.legal",
        ]
        for q in agent_queues_to_check:
            depth = _r.llen(q)
            if depth > circuit_limit:
                print(f"[CLICKUP_OS] CIRCUIT BREAKER: {q} has {depth} items — halting dispatch", flush=True)
                # Release the lock since we're not dispatching
                _r.delete(lock_key)
                return ""

        chain_id = str(uuid.uuid4())

        # Load doctrine for the envelope
        doctrine = {}
        try:
            resp = requests.get(f"{API_BASE_URL}/doctrine", timeout=5)
            if resp.ok:
                doctrine = resp.json()
        except Exception:
            pass

        agent_queues = {
            "research": "queue.agent.research",
            "revenue":  "queue.agent.revenue",
            "sales":    "queue.agent.sales",
            "growth":   "queue.agent.growth",
            "legal":    "queue.agent.legal",
            "product":  "queue.agent.product",
            "code":     "queue.agent.code",
            "systems":  "queue.agent.systems",
        }
        queue = agent_queues.get(agent, "queue.agent.research")

        import redis
        redis_url = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)

        envelope = {
            "agent":     agent,
            "task_type": "offer_stack",
            "chain_id":  chain_id,
            "clickup_task_id": task_id,
            "payload": {
                "instruction": instruction,
                "agent":       agent,
                "chain_id":    chain_id,
                "task_type":   "offer_stack",
                "message":     instruction,
                "target":      instruction[:80],
            },
            "doctrine": doctrine,
        }

        r.rpush(queue, json.dumps(envelope))
        print(f"[CLICKUP_OS] Dispatched {agent} for task {task_id} (chain: {chain_id[:8]})", flush=True)
        return chain_id

    except Exception as e:
        print(f"[CLICKUP_OS] Dispatch failed: {e}", flush=True)
        return ""

# ── Memory sync ───────────────────────────────────────────────────────────────

def sync_to_memory(task: dict, direction: dict, agent: str) -> None:
    """Sync pivots and new direction to Jarvis + agent memory."""
    if not direction.get("memory_update"):
        return

    memory_note = f"""
## {datetime.now().strftime('%Y-%m-%d %H:%M')} — ClickUp Direction from Curtis
Task: {task.get('name', '')} ({task.get('id', '')})
Direction: {direction['memory_update'][:500]}
Agent assigned: {agent}
Pivot: {direction.get('is_pivot', False)}
"""
    # Write to Jarvis memory
    jarvis_memory = MEMORY_BASE / "jarvis" / "core.md"
    jarvis_memory.parent.mkdir(parents=True, exist_ok=True)
    with open(jarvis_memory, "a") as f:
        f.write(memory_note)

    # Write to agent memory
    agent_memory = MEMORY_BASE / "agents" / agent / "core.md"
    agent_memory.parent.mkdir(parents=True, exist_ok=True)
    with open(agent_memory, "a") as f:
        f.write(memory_note)

    print(f"[CLICKUP_OS] Memory synced for {agent}: {direction['memory_update'][:80]}", flush=True)

# ── Completion poster ─────────────────────────────────────────────────────────

def post_completion_to_clickup(task_id: str, agent: str, report_path: str, chain_id: str) -> None:
    """
    Poll for agent completion and post structured result to ClickUp.
    Runs in a background thread after dispatch.
    """
    import threading

    def _poll_and_post():
        # Wait for agent to complete (poll report file)
        max_wait = 300  # 5 minutes
        start = time.time()
        report_text = ""

        # Try both container path and host path
        _rp = report_path if 'report_path' in dir() else rp
        host_path = _rp.replace("/ai-firm/", "/srv/silentempire/ai-firm/")
        while time.time() - start < max_wait:
            time.sleep(15)
            for check_path in [Path(host_path), Path(report_path)]:
                if check_path.exists() and check_path.stat().st_size > 100:
                    report_text = check_path.read_text()[:3000]
                    report_path = str(check_path)  # use whichever path worked
                    break
            if report_text:
                break

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

        # PATCH3_GDRIVE_COMPLETION
        # Try to save to Google Drive
        gdrive_url = ""
        gdrive_folder = ""
        if report_text:
            try:
                import subprocess as _sp
                gdrive_cli = "/srv/silentempire/ai-firm/tools/google_drive_cli.py"
                doc_title  = f"{datetime.now().strftime('%Y-%m-%d')} — {agent.title()} — {Path(report_path).stem[:60]}"
                host_rp = report_path.replace("/ai-firm/", "/srv/silentempire/ai-firm/")
                gd_result  = _sp.run(
                    ["python3", gdrive_cli, "agent-save", agent, host_rp, doc_title],
                    capture_output=True, text=True, timeout=60
                )
                if gd_result.returncode == 0:
                    for line in gd_result.stdout.split("\n"):
                        if line.startswith("URL:"):
                            gdrive_url = line.split("URL:", 1)[1].strip()
                        if line.startswith("Folder:"):
                            gdrive_folder = line.split("Folder:", 1)[1].strip()
                    print(f"[CLICKUP_OS] Google Doc created: {gdrive_url}", flush=True)
            except Exception as _gde:
                print(f"[CLICKUP_OS] Google Drive upload failed: {_gde}", flush=True)

        if report_text:
            summary = ""
            if "COMPLETION_SUMMARY:" in report_text:
                summary = report_text.split("COMPLETION_SUMMARY:")[1].split("\n")[0].strip()
            else:
                summary = report_text[:400].replace("\n", " ")

            gdrive_section = ""
            if gdrive_url:
                gdrive_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📁 GOOGLE DRIVE DELIVERABLE
Document: {doc_title}
URL: {gdrive_url}
Folder: {gdrive_folder}
Local Backup: {report_path}"""

            comment = f"""✅ {agent.upper()} AGENT COMPLETE — {ts}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 SUMMARY
{summary or '(see report)'}
{gdrive_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Engine: Silent Empire AI Agent System
Agent: {agent.title()} Agent | Chain: {chain_id[:8]}"""
        else:
            comment = f"""⏳ {agent.upper()} AGENT — {ts}
Task dispatched. Report not yet available at:
{report_path}
Chain ID: {chain_id[:8]}"""

        post_comment(task_id, comment)

        # Update custom fields
        if report_text:
            deliverable_val = gdrive_url if gdrive_url else f"Local: {report_path}"
            update_custom_field(task_id, FIELD_DELIVERABLE, deliverable_val)
            update_custom_field(task_id, FIELD_ACTION_ITEMS,
                "Review report and comment with next direction or approval")

        print(f"[CLICKUP_OS] Posted completion to task {task_id}", flush=True)

    thread = threading.Thread(target=_poll_and_post, daemon=True)
    thread.start()

# ── Dynamic field reader ──────────────────────────────────────────────────────

def get_all_custom_fields_for_list(list_id: str) -> dict:
    """
    Read all custom field definitions for a list.
    Returns {field_name: field_id} dict.
    This allows Jarvis to work with new fields you add without code changes.
    """
    data = cu_get(f"/list/{list_id}/field")
    fields = {}
    for f in data.get("fields", []):
        fields[f.get("name", "")] = {
            "id":   f.get("id", ""),
            "type": f.get("type", ""),
        }
    return fields

# ── Main scan loop ────────────────────────────────────────────────────────────

def scan_once(cfg: dict) -> int:
    """
    Single scan pass. Returns number of tasks acted on.
    """
    scan_lists = get_scan_lists(cfg)
    # PATCH2B_DISPATCH_CAP
    acted_on = 0
    dispatches_this_scan = 0

    # Load max dispatches per scan from config
    max_dispatches = 3
    try:
        max_dispatches = cfg.get("clickup", {}).get("max_dispatches_per_scan", 3)
    except Exception:
        pass

    for list_name, list_id in scan_lists.items():
        if dispatches_this_scan >= max_dispatches:
            print(f"[CLICKUP_OS] Dispatch cap ({max_dispatches}) reached for this scan cycle", flush=True)
            break
        # Skip excluded lists (secondary check — get_scan_lists filters most, this catches dynamic additions)
        _cu_cfg2 = cfg.get("clickup", {})
        _excl_lists = set(str(x) for x in _cu_cfg2.get("excluded_lists", []))
        if str(list_id) in _excl_lists:
            print(f"[CLICKUP_OS] Skipping excluded list {list_id}", flush=True)
            continue
        try:
            tasks = get_list_tasks(list_id)
            for task_stub in tasks:
                if dispatches_this_scan >= max_dispatches:
                    break
                task_id = task_stub.get("id")
                if not task_id:
                    continue

                # Quick check — any new Curtis comments?
                new_comments = get_new_curtis_comments(task_id)
                if not new_comments:
                    continue

                print(f"[CLICKUP_OS] New direction from Curtis on: {task_stub.get('name','?')[:60]}", flush=True)

                # Get full task with all custom fields + subtasks (7 levels deep)
                task = get_task_full(task_id, depth=0, max_depth=7)
                if not task:
                    continue

                # Process each new comment
                for comment in new_comments:
                    comment_text = comment.get("comment_text", "")
                    if not comment_text or len(comment_text) < 5:
                        continue

                    direction = extract_direction(comment_text)

                    # Check prerequisites
                    prereqs_met, prereq_reason = check_prerequisites_met(task)
                    if not prereqs_met:
                        post_comment(task_id, f"⚠️ Jarvis: Prerequisites not met — {prereq_reason}\nWill proceed once blockers are cleared.")
                        continue

                    # Determine agent
                    agent = classify_task_agent(task.get("name", ""), task.get("description", ""))

                    # Sync memory if pivot/approval
                    sync_to_memory(task, direction, agent)

                    # Build instruction and dispatch
                    instruction = build_agent_instruction(task, direction, agent)

                    # Post acknowledgment immediately
                    ack = f"""🤖 Jarvis received your direction on: {task.get('name','')[:60]}

Dispatching: {agent.title()} Agent
Direction: {comment_text[:200]}{'...' if len(comment_text) > 200 else ''}

Will post results here when complete. Chain tracking active."""
                    post_comment(task_id, ack)

                    # Dispatch agent
                    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
                    slug = re.sub(r'[^a-z0-9]+', '-', task.get('name','task')[:40].lower()).strip('-')
                    report_path = f"/ai-firm/data/reports/{agent}/{ts}_{slug}.md"
                    host_report_path = report_path.replace("/ai-firm/", "/srv/silentempire/ai-firm/")

                    chain_id = dispatch_to_agent(agent, instruction, task_id)

                    # Start background poller to post completion
                    if chain_id:
                        post_completion_to_clickup(task_id, agent, report_path, chain_id)
                        acted_on += 1
                        dispatches_this_scan += 1

                # Mark processed
                mark_task_processed(task_id, new_comments)

        except Exception as e:
            print(f"[CLICKUP_OS] Error scanning list {list_name}: {e}", flush=True)

    return acted_on


def clickup_scan_loop() -> None:
    """
    Main ClickUp scanner loop. Runs as a background thread.
    Interval controlled by autonomy_config.json clickup.scan_interval_minutes.
    """
    print("[CLICKUP_OS] Business OS scanner starting...", flush=True)
    time.sleep(30)  # Brief startup delay

    while True:
        try:
            cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

            # Check if enabled
            if not cfg.get("clickup", {}).get("scan_for_new_tasks", True):
                time.sleep(300)
                continue

            interval_min = cfg.get("clickup", {}).get("scan_interval_minutes",
                           cfg.get("intervals", {}).get("clickup_scan_minutes", 10))
            interval_sec = int(interval_min) * 60

            acted = scan_once(cfg)
            if acted > 0:
                print(f"[CLICKUP_OS] Scan complete — acted on {acted} task(s)", flush=True)

            time.sleep(interval_sec)

        except Exception as e:
            print(f"[CLICKUP_OS] Loop error: {e}", flush=True)
            time.sleep(60)


# ── Standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ClickUp Business OS Scanner")
    parser.add_argument("--scan-once", action="store_true", help="Run one scan pass and exit")
    parser.add_argument("--list-id", help="Scan a specific list ID")
    parser.add_argument("--task-id", help="Get full detail on a specific task")
    args = parser.parse_args()

    if args.task_id:
        task = get_task_full(args.task_id)
        print(json.dumps(task, indent=2))
        sys.exit(0)

    if args.scan_once:
        cfg = {}
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text())
        if args.list_id:
            cfg.setdefault("clickup", {})["scan_lists"] = {"custom": args.list_id}
        n = scan_once(cfg)
        print(f"Acted on {n} tasks.")
        sys.exit(0)

    clickup_scan_loop()
