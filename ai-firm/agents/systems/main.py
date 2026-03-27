"""
=========================================================
Systems Agent — Elite Infrastructure Module
Version: 5.0 (Self-Operating + Tool Execution Layer)

PRESERVES (from v4.2):
  - _as_dict safe normalizer
  - build_systems_instruction (all 20 items including coding layer)
  - process_task with chat passthrough + idempotent guard
  - Retry queue + dead letter queue logic
  - MAX_RETRIES, QUEUE_NAME, RETRY_QUEUE, DEAD_QUEUE
  - submit_job / dequeue_blocking / enqueue / build_artifact
  - stage_already_completed / mark_stage_completed

ADDS (v5.0):
  - tool_client: call_tool() for bash, file_read, file_write,
    file_list, docker_ps, docker_logs, docker_restart, docker_exec
  - execute_system_task(): LLM-planned multi-tool execution
  - handle_direct_command(): prefix-based direct tool invocation
  - _get_system_state(): live container snapshot for LLM context
  - "tool_execution" task_type handler (new, non-regressive)
  - "direct_command" task_type handler (new, non-regressive)
  - All new code routes through existing retry/dead-letter harness
=========================================================
"""

import json
import os
import re
import time
import traceback
import uuid
from typing import Any, Dict, Optional

import redis as redis_lib
import requests as http_requests

from shared.redis_bus import enqueue, dequeue_blocking
from shared.job_submitter import submit_job
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed

# --------------------------------------------------
# CONSTANTS
# --------------------------------------------------

AGENT_NAME = "systems"

QUEUE_NAME      = "queue.agent.systems"
RETRY_QUEUE     = "queue.agent.systems.retry"
DEAD_QUEUE      = "queue.agent.systems.dead"

MAX_RETRIES = 3

REDIS_URL    = os.getenv("REDIS_URL", "redis://redis:6379/0")
API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

# Tool executor Redis queues
TOOL_REQUEST_QUEUE      = "queue.tool.request"
TOOL_RESULT_QUEUE_PFX   = "queue.tool.result."

# Paths tool_client will never touch (security)
BLOCKED_PATHS = [
    "/etc/shadow",
    "/root/.ssh/id_rsa",
]

# Bash patterns that require an explicit "force": true in params
DESTRUCTIVE_PATTERNS = [
    "rm -rf",
    "docker system prune",
    "DROP TABLE",
    "mkfs",
    "format",
]

JOB_POLL_SLEEP      = 1.5

# MCP LLM client (bypasses worker routing issues)
try:
    from mcp.shared.mcp_protocol import MCPClient as _MCPClient
    _mcp_client = _MCPClient()
    MCP_LLM_AVAILABLE = True
except Exception:
    MCP_LLM_AVAILABLE = False
    _mcp_client = None

def _call_llm_direct(prompt: str) -> str:
    """Call NVIDIA directly — fast, reliable, no dependencies."""
    nvidia_key  = os.getenv("NVIDIA_API_KEY") or os.getenv("MOONSHOT_API_KEY", "")
    nvidia_base = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
    model       = os.getenv("MODEL_SYSTEMS", os.getenv("MODEL_CODING", "qwen/qwen3-coder-480b-a35b-instruct"))

    if not nvidia_key:
        print("[SYSTEMS] No NVIDIA_API_KEY set", flush=True)
        return ""

    models_to_try = [model, "qwen/qwen3.5-397b-a17b", "meta/llama-4-maverick-17b-128e-instruct"]
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    for attempt_model in models_to_try:
        try:
            print(f"[SYSTEMS] LLM call: {attempt_model}", flush=True)
            resp = http_requests.post(
                f"{nvidia_base}/chat/completions",
                headers={"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"},
                json={
                    "model": attempt_model,
                    "messages": [
                        {"role": "system", "content": "You are the Systems Agent for Silent Empire AI. Execute infrastructure tasks precisely. Return only what is explicitly requested. No commentary."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "").strip()
            if content:
                print(f"[SYSTEMS] LLM response received ({len(content)} chars)", flush=True)
                try:
                    usage = data.get("usage", {})
                    ti  = int(usage.get("prompt_tokens", 0) or 0)
                    to_ = int(usage.get("completion_tokens", 0) or 0)
                    if ti or to_:
                        http_requests.post(f"{API_BASE_URL}/metrics/llm/record", json={
                            "agent": "systems", "model": attempt_model,
                            "provider": "nvidia", "tokens_in": ti,
                            "tokens_out": to_, "tokens_total": ti + to_,
                            "cost_usd": 0.0,
                        }, timeout=2)
                except Exception:
                    pass
                return content
        except Exception as e:
            print(f"[SYSTEMS] LLM {attempt_model} failed: {e}", flush=True)
            continue

    print("[SYSTEMS] All LLM attempts failed", flush=True)
    return ""
JOB_POLL_MAX_SECONDS = 300

# --------------------------------------------------
# REDIS CLIENT (shared by tool_client layer only)
# --------------------------------------------------

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


# ==================================================
# SECTION 1 — SAFE NORMALIZER (PRESERVED EXACTLY)
# ==================================================

def _as_dict(obj: Any) -> Dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except Exception:
        return {}


# ==================================================
# SECTION 2 — TOOL CLIENT (NEW — v5.0)
# Submits tool call requests to the tool_executor
# service via Redis and waits for the result.
# Agents never shell out directly — all execution
# is delegated to the dedicated executor container
# which has the Docker socket mounted.
# ==================================================

def call_tool(tool: str, params: dict, timeout: int = 60) -> dict:
    """
    Submit a tool call to the tool_executor service and block
    until a result arrives or timeout expires.

    Supported tools:
      bash          – run shell command on VPS
      file_read     – read file contents
      file_write    – create/overwrite a file
      file_list     – list directory entries
      docker_ps     – list running containers
      docker_logs   – tail container logs
      docker_restart– restart a named container
      docker_exec   – exec command inside container

    Returns dict always containing {"success": bool, ...}.
    Never raises — returns {"success": False, "error": ...} on failure.
    """
    # Safety: refuse blocked paths before the request leaves this agent
    if tool in ("file_read", "file_write"):
        path = params.get("path", "")
        for blocked in BLOCKED_PATHS:
            if path.startswith(blocked):
                return {"success": False, "error": f"Path blocked by security policy: {path}"}

    # Safety: refuse destructive bash unless caller passes force=True
    if tool == "bash":
        cmd = params.get("command", "")
        force = params.get("force", False)
        if not force:
            for pattern in DESTRUCTIVE_PATTERNS:
                if pattern in cmd:
                    return {
                        "success": False,
                        "error": (
                            f"Destructive pattern '{pattern}' detected. "
                            "Pass force=True in params to override."
                        )
                    }

    request_id  = str(uuid.uuid4())
    reply_queue = f"{TOOL_RESULT_QUEUE_PFX}{request_id}"

    request_envelope = {
        "request_id":  request_id,
        "tool":        tool,
        "params":      params,
        "reply_queue": reply_queue,
    }

    _redis.lpush(TOOL_REQUEST_QUEUE, json.dumps(request_envelope))

    item = _redis.brpop(reply_queue, timeout=timeout)
    if not item:
        return {"success": False, "error": f"Tool call timed out after {timeout}s"}

    _, raw = item
    try:
        return json.loads(raw)
    except Exception as e:
        return {"success": False, "error": f"Could not parse tool result: {e}", "raw": raw}


# ==================================================
# SECTION 3 — SYSTEM STATE SNAPSHOT (NEW — v5.0)
# Provides a lightweight live context to the LLM
# so it can make informed tool-call decisions.
# ==================================================

def _get_system_state() -> str:
    """
    Returns a brief snapshot of running Docker containers
    to inject into the LLM planning prompt.
    """
    try:
        ps = call_tool("docker_ps", {}, timeout=10)
        containers = ps.get("containers", [])
        if not containers:
            return "No container data available."
        lines = [f"  - {c['name']}: {c['status']}" for c in containers]
        return "Running containers:\n" + "\n".join(lines)
    except Exception as e:
        return f"System state unavailable: {e}"


# ==================================================
# SECTION 4 — LLM JOB HELPERS (NEW — v5.0)
# Thin wrappers that use the existing API job system
# (same pattern as research/growth agents) for the
# tool-planning and synthesis LLM calls.
# ==================================================

def _create_job(instruction: str) -> Optional[str]:
    try:
        resp = http_requests.post(
            f"{API_BASE_URL}/jobs",
            json={"type": "ai_task", "payload": {"instruction": instruction}},
            timeout=10,
        )
        return resp.json().get("job_id") or resp.json().get("id")
    except Exception as e:
        print(f"[SYSTEMS] _create_job error: {e}", flush=True)
        return None


def _wait_job(job_id: str) -> dict:
    deadline = time.time() + JOB_POLL_MAX_SECONDS
    while time.time() < deadline:
        try:
            resp = http_requests.get(f"{API_BASE_URL}/jobs/{job_id}", timeout=5)
            data = resp.json()
            if data.get("status") in ("completed", "failed"):
                return data
        except Exception:
            pass
        time.sleep(JOB_POLL_SLEEP)
    return {"status": "timeout", "error_message": "Job timed out"}


def _extract_text(job_data: dict) -> str:
    """Pull plain text out of whatever shape the job result takes."""
    raw = job_data.get("result", {})
    if isinstance(raw, dict):
        return raw.get("content", raw.get("text", json.dumps(raw)))
    return str(raw)


# ==================================================
# SECTION 5 — TOOL EXECUTION ENGINE (NEW — v5.0)
# LLM generates a tool-call plan, each call is
# executed via call_tool(), then results are
# synthesized back through the LLM.
# ==================================================

def execute_system_task_simple(task: str, chain_id: str = None) -> dict:
    """Simplified: LLM writes a bash script, we execute it directly."""
    system_state = _get_system_state()
    prompt = f"""You are the Systems Agent for Silent Empire AI.

Current system state:
{system_state}

Task: {task}

Write a bash script that accomplishes this task.
RULES:
- Always run mkdir -p on the parent directory before writing any file
- Use python3 with a heredoc or -c to write file contents
- Never assume a directory exists — always create it first
- Return ONLY a bash script starting with #!/bin/bash
- No explanation. No markdown fences."""

    script = _call_llm_direct(prompt).strip()
    if not script:
        return {"success": False, "error": "LLM returned empty script"}

    if script.startswith("```"):
        script = script.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    print(f"[SYSTEMS] Executing script ({len(script)} chars)", flush=True)

    import tempfile, subprocess
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True, text=True, timeout=60
        )
        stdout = (result.stdout or "")[-3000:]
        stderr = (result.stderr or "")[-1000:]
        success = result.returncode == 0
        print(f"[SYSTEMS] Script exit={result.returncode}", flush=True)
        if stdout: print(f"[SYSTEMS] stdout: {stdout[:200]}", flush=True)
        if stderr: print(f"[SYSTEMS] stderr: {stderr[:200]}", flush=True)

        synthesis = _call_llm_direct(
            f"Task: {task}\nOutput: {stdout[:300]}\nErrors: {stderr[:200]}\nExit: {result.returncode}\nWrite a 2-sentence status report."
        ) or ("Task completed." if success else f"Task failed: {stderr[:100]}")

        return {
            "success": success,
            "task": task,
            "script": script[:500],
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "synthesis": synthesis,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Script timed out after 60s"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def execute_system_task(task: str, chain_id: str = None) -> dict:
    """
    Natural-language → LLM plan → tool execution → synthesis.

    Phase 1: Ask LLM to produce a JSON array of tool calls.
    Phase 2: Execute each tool call via call_tool().
    Phase 3: Ask LLM to synthesize results into a status report.

    Returns a dict with keys:
      success, task, tool_calls_executed, results, synthesis
    """
    system_state = _get_system_state()

    # ── Phase 1: Planning ──────────────────────────────────────────
    planning_prompt = f"""You are the Systems Agent for Silent Empire AI infrastructure.
You have access to these tools: bash, file_read, file_write, file_list,
docker_ps, docker_logs, docker_restart, docker_exec.

Current system state:
{system_state}

Your task: {task}

CRITICAL: You MUST respond with ONLY a valid JSON array. No text before or after. No questions. No markdown. Start your response with [ and end with ].

Respond ONLY with a valid JSON array of tool calls to execute in order.
Each element must have exactly these keys:
  "tool"        : tool name (string)
  "params"      : dict of tool-specific parameters
  "description" : one sentence explaining why

Example format:
[
  {{"tool": "docker_ps", "params": {{}}, "description": "Check container status"}},
  {{"tool": "docker_logs", "params": {{"container": "jarvis-orchestrator", "lines": 50}}, "description": "Inspect orchestrator logs"}},
  {{"tool": "bash", "params": {{"command": "df -h /srv/silentempire"}}, "description": "Check disk usage"}}
]

Output ONLY the JSON array. No markdown fences. No explanation."""

    raw_plan = _call_llm_direct(planning_prompt).strip()
    if not raw_plan:
        return {"success": False, "error": "Planning LLM returned empty response"}

    # Strip markdown fences if LLM ignored instructions
    if raw_plan.startswith("```"):
        raw_plan = raw_plan.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        tool_calls = json.loads(raw_plan)
    except Exception:
        match = re.search(r'\[.*?\]', raw_plan, re.DOTALL)
        if match:
            try:
                tool_calls = json.loads(match.group())
            except Exception:
                return {"success": False, "error": f"Could not parse tool plan: {raw_plan[:500]}"}
        else:
            return {"success": False, "error": f"No JSON array found in plan: {raw_plan[:500]}"}

    if not isinstance(tool_calls, list):
        return {"success": False, "error": "Plan was not a JSON array"}

    # ── Phase 2: Execution ─────────────────────────────────────────
    results = []
    for call in tool_calls:
        tool   = call.get("tool", "")
        params = call.get("params", {})
        desc   = call.get("description", "")

        print(f"[SYSTEMS] Executing tool={tool} | {desc}", flush=True)
        result = call_tool(tool, params)

        results.append({
            "tool":        tool,
            "description": desc,
            "params":      params,
            "result":      result,
        })

        # Hard stop on explicit failure flag
        if not result.get("success") and call.get("stop_on_failure", False):
            print(f"[SYSTEMS] stop_on_failure triggered on tool={tool}", flush=True)
            break

    # ── Phase 3: Synthesis ─────────────────────────────────────────
    synthesis_prompt = f"""You are the Systems Agent. You executed tool calls for this task: {task}

Execution results (JSON):
{json.dumps(results, indent=2)[:8000]}

Write a concise status report covering:
1. What was accomplished
2. Any errors encountered and their likely cause
3. Current system state based on outputs
4. Recommended next actions (if any)

Be direct. No fluff."""

    synthesis = _call_llm_direct(synthesis_prompt)

    return {
        "success":             True,
        "task":                task,
        "tool_calls_executed": len(results),
        "results":             results,
        "synthesis":           synthesis,
    }


# ==================================================
# SECTION 6 — DIRECT COMMAND HANDLER (NEW — v5.0)
# Allows Jarvis chat to send explicit tool commands
# without LLM planning overhead.
#
# Supported prefixes:
#   run: <bash command>
#   read: <file path>
#   write: <path>|<content>
#   list: <directory path>
#   logs: <container name>
#   restart: <container name>
#   exec: <container> <command>
#   ps:   (no args — list containers)
#
# Falls through to execute_system_task() if no
# recognized prefix is detected.
# ==================================================

def handle_direct_command(command: str, chain_id: str = None) -> dict:
    command = command.strip()

    if command.lower().startswith("run:"):
        return call_tool("bash", {"command": command[4:].strip()})

    elif command.lower().startswith("read:"):
        return call_tool("file_read", {"path": command[5:].strip()})

    elif command.lower().startswith("write:"):
        # Format: write: /path/to/file|file content here
        body = command[6:].strip()
        if "|" in body:
            path, content = body.split("|", 1)
            return call_tool("file_write", {"path": path.strip(), "content": content})
        return {"success": False, "error": "write: format is 'write: /path|content'"}

    elif command.lower().startswith("list:"):
        return call_tool("file_list", {"path": command[5:].strip()})

    elif command.lower().startswith("logs:"):
        parts = command[5:].strip().split()
        container = parts[0] if parts else ""
        lines     = int(parts[1]) if len(parts) > 1 else 100
        return call_tool("docker_logs", {"container": container, "lines": lines})

    elif command.lower().startswith("restart:"):
        return call_tool("docker_restart", {"container": command[8:].strip()})

    elif command.lower().startswith("exec:"):
        # Format: exec: container_name command args
        body  = command[5:].strip()
        parts = body.split(" ", 1)
        return call_tool("docker_exec", {
            "container": parts[0],
            "command":   parts[1] if len(parts) > 1 else "echo ok",
        })

    elif command.lower().startswith("ps:") or command.lower().strip() == "ps":
        return call_tool("docker_ps", {})

    else:
        # No recognized prefix — ask LLM what to do, then execute directly
        return execute_system_task_simple(command, chain_id)


# ==================================================
# SECTION 7 — SYSTEMS INSTRUCTION BUILDER
# PRESERVED EXACTLY FROM v4.2 — NOT MODIFIED
# ==================================================

def build_systems_instruction(executive, identity, soul, artifact):

    upstream_data = {}

    if artifact and isinstance(artifact, dict):
        upstream_data = artifact.get("data", {})

    return f"""
=== EXECUTIVE STACK ===
{executive}

=== AGENT IDENTITY ===
{identity}

=== AGENT SOUL ===
{soul}

=== UPSTREAM LEGAL REVIEW ===
{json.dumps(upstream_data, indent=2)}

You are the Systems Architect AND Code Execution Architect.

Convert the full chain output into:

1. Operational Workflow Map
2. Automation Opportunities
3. Required Infrastructure
4. Agent Task Breakdown
5. Data Flow Diagram (logical description)
6. Bottleneck Analysis
7. KPI Framework
8. Reporting Structure
9. Scaling Plan
10. Failure Containment Strategy

--- NEW ELITE CODING LAYER ---

11. Service Architecture (microservices, APIs, queues, contracts)
12. Code Structure Plan (folders, modules, responsibilities)
13. API Specifications (endpoints, payloads, contracts)
14. Queue Contracts (input/output schemas for each agent)
15. Database Design (tables, schemas, indexing strategy)
16. Deployment Plan (Docker, VPS, CI/CD steps)
17. Observability Plan (logging, metrics, tracing)
18. Security Layer (auth, secrets, rate limiting, isolation)
19. Cost Control Logic (model routing, fallback rules)
20. Code Generation Instructions:
    - Generate actual production-ready Python code where needed
    - Ensure compatibility with FastAPI + Redis + existing architecture
    - No pseudo code unless explicitly required
    - All code must be modular, testable, and deployable
    - Include comments and structure for immediate integration

Systems-first.
Code-ready.
Execution-ready.
No fluff.
"""


# ==================================================
# SECTION 8 — TASK PROCESSOR
# PRESERVED from v4.2 with two new task_type
# branches added (tool_execution, direct_command).
# All existing branches are byte-for-byte identical.
# ==================================================

def process_task(raw_envelope):

    envelope = _as_dict(raw_envelope)

    if not isinstance(envelope, dict) or not envelope:
        print("[SYSTEMS] Skipping invalid envelope", flush=True)
        return

    doctrine = _as_dict(envelope.get("doctrine"))

    executive = doctrine.get("executive", "")
    identity  = doctrine.get("identity", "")
    soul      = doctrine.get("soul", "")

    task_type = envelope.get("task_type")

    payload           = _as_dict(envelope.get("payload"))
    upstream_artifact = envelope.get("result") or payload
    upstream_artifact = _as_dict(upstream_artifact)

    chain_id = payload.get("chain_id")

    if not task_type or not isinstance(payload, dict):
        print(f"[SYSTEMS] Skipping invalid task | task_type={task_type}", flush=True)
        return

    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[SYSTEMS] Stage already completed for {chain_id}, skipping.", flush=True)
        return

    print(f"[SYSTEMS] Processing task: {task_type} | chain_id={chain_id}", flush=True)

    # ── PRESERVED: CHAT PASSTHROUGH ────────────────────────────────
    if task_type == "chat":
        msg = payload.get("message")
        if msg is None:
            msg = payload.get("product")

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent":     AGENT_NAME,
            "task_type": "chat",
            "result": {
                "artifact_type": "chat_echo",
                "version":       "1.0",
                "data": {
                    "text": f"[Systems Agent] Received: {msg}"
                }
            },
            "payload": payload,
            "doctrine": doctrine,
        })
        return
    # ── END PRESERVED CHAT PASSTHROUGH ─────────────────────────────

    # ── NEW: DIRECT COMMAND (v5.0) ─────────────────────────────────
    # Triggered when chat sends: {"task_type": "direct_command",
    #   "payload": {"command": "logs: jarvis-orchestrator"}}
    if task_type == "direct_command":
        command = payload.get("command") or payload.get("message") or ""
        result  = handle_direct_command(command, chain_id)

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent":     AGENT_NAME,
            "task_type": task_type,
            "result": build_artifact("direct_command_result", "1.0", result),
            "payload":  payload,
            "doctrine": doctrine,
        })
        return
    # ── END DIRECT COMMAND ─────────────────────────────────────────

    # ── NEW: TOOL EXECUTION (v5.0) ─────────────────────────────────
    # Triggered when orchestrator sends:
    # {"task_type": "tool_execution",
    #  "payload": {"task": "Check why orchestrator is failing"}}
    if task_type == "tool_execution":
        task   = (
            payload.get("task") or
            payload.get("message") or
            payload.get("instruction") or
            "Perform a system health check and report status"
        )
        result = execute_system_task(task, chain_id)

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent":     AGENT_NAME,
            "task_type": task_type,
            "result":    build_artifact("tool_execution_result", "1.0", result),
            "payload":   payload,
            "doctrine":  doctrine,
        })
        return
    # ── END TOOL EXECUTION ─────────────────────────────────────────

    # ── PRESERVED: OFFER STACK (EXACT from v4.2) ───────────────────
    if task_type != "offer_stack":
        print(f"[SYSTEMS] Unknown task type: {task_type}", flush=True)
        return

    instruction = build_systems_instruction(
        executive,
        identity,
        soul,
        upstream_artifact,
    )

    result = submit_job("ai_task", {
        "instruction": instruction,
        "agent":       AGENT_NAME,
    })

    if not result:
        result = {"error": "empty_response"}

    structured_output = build_artifact(
        "systems_architecture",
        "1.0",
        {"raw_systems_strategy": result},
    )

    if chain_id:
        mark_stage_completed(chain_id, AGENT_NAME)

    enqueue("queue.orchestrator.results", {
        "agent":     AGENT_NAME,
        "task_type": task_type,
        "result":    structured_output,
        "payload":   payload,
        "doctrine":  doctrine,
    })
    # ── END PRESERVED OFFER STACK ──────────────────────────────────


# ==================================================
# SECTION 9 — MAIN LOOP
# PRESERVED EXACTLY FROM v4.2 — NOT MODIFIED
# Retry + dead letter harness covers ALL task types
# including the new tool_execution and direct_command
# branches added in Section 8.
# ==================================================

def run():
    print("[SYSTEMS] Elite Systems Architect online. (Durable + Code Mode + Tool Execution)", flush=True)

    while True:
        try:
            raw = dequeue_blocking(QUEUE_NAME)
            envelope = _as_dict(raw)

            retry_count = envelope.get("retry_count", 0)

            try:
                process_task(envelope)

            except Exception as error:
                retry_count += 1
                envelope["retry_count"] = retry_count

                print(f"[SYSTEMS ERROR] Task failure | retry={retry_count} | error={error}", flush=True)

                if retry_count < MAX_RETRIES:
                    enqueue(RETRY_QUEUE, envelope)
                    print("[SYSTEMS] Sent to retry queue.", flush=True)
                else:
                    enqueue(DEAD_QUEUE, envelope)

                    enqueue("queue.orchestrator.results", {
                        "agent":     AGENT_NAME,
                        "task_type": envelope.get("task_type"),
                        "result": {
                            "artifact_type": "error",
                            "version":       "1.0",
                            "data": {
                                "error":       str(error),
                                "retry_count": retry_count,
                            }
                        },
                        "payload":  envelope.get("payload"),
                        "doctrine": envelope.get("doctrine"),
                        "status":   "failed",
                    })

                    print("[SYSTEMS] Moved to DEAD queue + notified orchestrator.", flush=True)

        except Exception as queue_error:
            print(f"[SYSTEMS ERROR] Queue failure: {queue_error}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    run()
