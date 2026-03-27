"""
=========================================================
Code Agent — Silent Empire Elite Development Module
Version: 1.0

Purpose:
  Dedicated autonomous code writing, testing, and deployment.
  Separate from Systems Agent which handles infrastructure.
  This agent BUILDS things — apps, features, tools, pages.

Capabilities:
  - Write complete Python / JavaScript / React / HTML files
  - Read existing code before modifying (no blind writes)
  - Run tests via MCP infra bash tool
  - Deploy by restarting relevant containers via MCP infra
  - Build new API endpoints and register them
  - Create Mission Control UI components
  - Build client-facing tools and pages
  - Modify its own agent siblings (self-improvement)

Task types handled:
  - "code_task"       : natural language → write/modify code
  - "build_feature"   : full feature from spec to deployment
  - "code_review"     : review existing code, return findings
  - "write_test"      : generate test file for a module
  - "offer_stack"     : chain mode (receives upstream context)
  - "chat"            : passthrough

MCP tools used:
  - filesystem.read       : read existing code before writing
  - filesystem.write      : write new/modified code
  - filesystem.search     : find relevant code across codebase
  - filesystem.list       : explore directory structure
  - infra.bash            : run tests, linters
  - infra.docker_restart  : deploy after writing
  - infra.docker_logs     : verify deployment succeeded
  - memory.get_chain_summary : get upstream context efficiently
  - memory.store_result   : store output for downstream agents
  - llm_router.run        : execute LLM calls centrally
=========================================================
"""

import json
import os
import re
import time
import traceback
from typing import Any, Dict, Optional, List

import sys
sys.path.insert(0, "/ai-firm")

from shared.redis_bus import enqueue, dequeue_blocking
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed

# --------------------------------------------------
# CONSTANTS
# --------------------------------------------------

AGENT_NAME  = "code"
QUEUE_NAME  = "queue.agent.code"
RETRY_QUEUE = "queue.agent.code.retry"
DEAD_QUEUE  = "queue.agent.code.dead"
MAX_RETRIES = 3

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
REDIS_URL    = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")

# --------------------------------------------------
# MCP CLIENT
# --------------------------------------------------

try:
    from mcp.shared.mcp_protocol import MCPClient
    _mcp = MCPClient()
    MCP_AVAILABLE = True
    print("[CODE] MCP client loaded.", flush=True)
except Exception as e:
    print(f"[CODE] MCP unavailable: {e}", flush=True)
    MCP_AVAILABLE = False
    _mcp = None


def mcp(server: str, tool: str, params: dict, fallback=None):
    if not MCP_AVAILABLE or _mcp is None:
        return fallback
    try:
        return _mcp.call_tool(server, tool, params, timeout=45)
    except Exception as e:
        print(f"[CODE] MCP {server}.{tool} failed: {e}", flush=True)
        return fallback


# --------------------------------------------------
# SAFE NORMALIZER
# --------------------------------------------------

def _as_dict(obj: Any) -> Dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8", errors="replace")
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return parsed if isinstance(parsed, dict) else {"_value": parsed}
        except Exception:
            return {}
    try:
        return dict(obj)
    except Exception:
        return {}


# --------------------------------------------------
# LLM CALL VIA MCP ROUTER
# Falls back to direct API call if MCP unavailable
# --------------------------------------------------

import requests as _http

def call_llm(messages: List[dict], role: str = "code", max_tokens: int = 4096) -> str:
    # Try MCP router first (centralized cost tracking)
    if MCP_AVAILABLE:
        result = mcp("llm_router", "run", {
            "model":      mcp("llm_router", "get_model_for_role", {"role": role}) or "qwen/qwen3.5-122b-a10b",
            "messages":   messages,
            "agent":      AGENT_NAME,
        })
        if result and result.get("content"):
            return result["content"]

    # Direct fallback
    nvidia_key  = os.getenv("NVIDIA_API_KEY") or os.getenv("MOONSHOT_API_KEY")
    nvidia_base = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")

    if nvidia_key:
        try:
            resp = _http.post(
                f"{nvidia_base}/chat/completions",
                headers={"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"},
                json={"model": os.getenv("MODEL_CODING", "qwen/qwen3.5-122b-a10b"),
                      "messages": messages, "temperature": 0.2, "max_tokens": max_tokens},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[CODE] Direct LLM call failed: {e}", flush=True)

    return ""


# --------------------------------------------------
# CODE EXTRACTION
# Pull code blocks out of LLM response
# --------------------------------------------------

def extract_code_blocks(text: str) -> List[dict]:
    """
    Extracts all fenced code blocks from LLM output.
    Returns list of {language, code} dicts.
    """
    pattern = r"```(\w+)?\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    blocks = []
    for lang, code in matches:
        blocks.append({
            "language": lang.strip() if lang else "text",
            "code": code.strip()
        })
    return blocks


def extract_file_writes(text: str) -> List[dict]:
    """
    Extracts structured file write instructions from LLM output.
    Looks for patterns like:
      FILE: /path/to/file.py
      ```python
      <code>
      ```
    """
    writes = []
    # Pattern: FILE: <path> followed by code block
    file_pattern = r"FILE:\s*(/[^\n]+)\n```(?:\w+)?\n(.*?)```"
    matches = re.findall(file_pattern, text, re.DOTALL)
    for path, code in matches:
        writes.append({
            "path": path.strip(),
            "content": code.strip()
        })
    return writes


# --------------------------------------------------
# READ EXISTING CODE BEFORE WRITING
# Prevents blind overwrites — agent always reads first
# --------------------------------------------------

def read_existing(path: str) -> Optional[str]:
    result = mcp("filesystem", "read", {"path": path})
    if result and "content" in result:
        return result["content"]
    return None


def write_file(path: str, content: str) -> bool:
    result = mcp("filesystem", "write", {"path": path, "content": content})
    if result and result.get("status") == "written":
        print(f"[CODE] Written: {path}", flush=True)
        return True
    print(f"[CODE] Write failed: {path}", flush=True)
    return False


def run_test(command: str) -> dict:
    result = mcp("infra", "bash", {"command": command, "timeout": 30})
    return result or {"exit_code": -1, "stdout": "", "stderr": "MCP unavailable"}


# --------------------------------------------------
# CORE: EXECUTE A CODE TASK
# The main brain — takes natural language task,
# reads relevant code, writes solution, optionally deploys
# --------------------------------------------------

def execute_code_task(task: str, context: str = "", chain_id: str = None) -> dict:
    """
    Full autonomous code execution:
    1. Understand what needs to be built/changed
    2. Read existing relevant code
    3. Generate solution
    4. Write files
    5. Run syntax check
    6. Optionally restart service
    7. Return structured result
    """
    print(f"[CODE] Executing task: {task[:100]}", flush=True)

    # Step 1: Plan — what files need to be read/written?
    plan_messages = [
        {
            "role": "system",
            "content": (
                "You are the Code Agent for Silent Empire AI. "
                "You write production-ready Python, JavaScript, and React code. "
                "You have access to the filesystem at /srv/silentempire/ai-firm and /srv/silentempire/app. "
                "Always read existing files before modifying them. "
                "Return ONLY valid JSON. No markdown, no explanation outside the JSON."
            )
        },
        {
            "role": "user",
            "content": f"""Task: {task}

Context from upstream agents:
{context or 'None'}

Return a JSON plan:
{{
  "files_to_read": ["/path/to/existing/file.py"],
  "files_to_write": [
    {{
      "path": "/path/to/output/file.py",
      "description": "what this file does"
    }}
  ],
  "test_command": "python3 -m py_compile /path/to/file.py",
  "restart_service": "container-name-or-empty-string",
  "summary": "one sentence what this task accomplishes"
}}"""
        }
    ]

    plan_raw = call_llm(plan_messages, role="code")

    # Parse plan
    plan = {}
    try:
        clean = plan_raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
        plan = json.loads(clean)
    except Exception:
        match = re.search(r'\{.*\}', plan_raw, re.DOTALL)
        if match:
            try:
                plan = json.loads(match.group())
            except Exception:
                pass

    files_to_read    = plan.get("files_to_read", [])
    files_to_write   = plan.get("files_to_write", [])
    test_command     = plan.get("test_command", "")
    restart_service  = plan.get("restart_service", "")
    summary          = plan.get("summary", task[:100])

    # Step 2: Read existing files
    existing_code = {}
    for path in files_to_read[:5]:  # cap at 5 reads
        content = read_existing(path)
        if content:
            existing_code[path] = content[:3000]  # cap per file

    # Step 3: Generate code
    existing_summary = ""
    if existing_code:
        parts = []
        for path, content in existing_code.items():
            parts.append(f"=== {path} ===\n{content}")
        existing_summary = "\n\n".join(parts)

    write_targets = "\n".join(
        f"- {f['path']}: {f.get('description', '')}"
        for f in files_to_write
    )

    code_messages = [
        {
            "role": "system",
            "content": (
                "You are the Code Agent for Silent Empire AI. "
                "Write production-ready, deployable code. "
                "No placeholder comments like '# implement this'. "
                "No pseudo-code. Real, working code only. "
                "For each file, output exactly: FILE: /full/path/to/file.ext then a code block."
            )
        },
        {
            "role": "user",
            "content": f"""Task: {task}

Files to write:
{write_targets}

Existing code (read for context):
{existing_summary or 'No existing files to read.'}

Upstream context:
{context or 'None'}

For each file output:
FILE: /full/path/to/file.ext
```language
<complete file content>
```

Write ALL files. Complete implementations only."""
        }
    ]

    code_output = call_llm(code_messages, role="code", max_tokens=4096)

    # Step 4: Extract and write files
    file_writes = extract_file_writes(code_output)
    written_files = []
    write_errors  = []

    for fw in file_writes:
        path    = fw["path"]
        content = fw["content"]
        if write_file(path, content):
            written_files.append(path)
        else:
            write_errors.append(path)

    # If no structured FILE: blocks found, try raw code blocks
    if not file_writes and files_to_write:
        blocks = extract_code_blocks(code_output)
        for i, (target, block) in enumerate(zip(files_to_write, blocks)):
            path = target["path"]
            if write_file(path, block["code"]):
                written_files.append(path)
            else:
                write_errors.append(path)

    # Step 5: Syntax check
    test_result = {}
    if test_command and written_files:
        test_result = run_test(test_command)
        if test_result.get("exit_code", 0) != 0:
            print(f"[CODE] Test failed: {test_result.get('stderr', '')[:200]}", flush=True)

    # Step 6: Restart service if needed
    restart_result = {}
    if restart_service and written_files and not write_errors:
        restart_result = mcp("infra", "docker_restart", {"container": restart_service}) or {}
        print(f"[CODE] Restarted {restart_service}: {restart_result.get('status', '?')}", flush=True)

        # Give container 3 seconds then check logs
        time.sleep(3)
        logs = mcp("infra", "docker_logs", {"container": restart_service, "lines": 20}) or ""
        restart_result["logs"] = logs

    # Store result in memory for downstream agents
    if chain_id and MCP_AVAILABLE:
        mcp("memory", "store_result", {
            "chain_id": chain_id,
            "agent": AGENT_NAME,
            "data": {
                "summary": summary,
                "written_files": written_files,
                "test_passed": test_result.get("exit_code", 0) == 0,
            }
        })

    return {
        "success":       len(written_files) > 0,
        "summary":       summary,
        "task":          task,
        "written_files": written_files,
        "write_errors":  write_errors,
        "test_result":   test_result,
        "restart":       restart_result,
        "code_output":   code_output[:2000],  # truncated for artifact
    }


# --------------------------------------------------
# BUILD FEATURE (full spec-to-deploy workflow)
# --------------------------------------------------

def build_feature(spec: str, chain_id: str = None) -> dict:
    """
    Takes a feature specification and builds it end to end:
    1. Break spec into sub-tasks
    2. Execute each sub-task in order
    3. Return full build report
    """
    print(f"[CODE] Building feature: {spec[:100]}", flush=True)

    # Decompose spec into ordered tasks
    decompose_messages = [
        {
            "role": "system",
            "content": (
                "You are a senior software architect. "
                "Break feature specs into ordered, atomic coding tasks. "
                "Return ONLY a JSON array of task strings. No markdown."
            )
        },
        {
            "role": "user",
            "content": f"""Feature spec: {spec}

Return a JSON array of ordered tasks:
["task 1", "task 2", "task 3"]

Each task should be one atomic coding operation.
Maximum 5 tasks. Be specific about file paths."""
        }
    ]

    tasks_raw = call_llm(decompose_messages, role="code")
    tasks = []
    try:
        clean = tasks_raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
        tasks = json.loads(clean)
    except Exception:
        tasks = [spec]  # fallback: treat whole spec as single task

    # Execute each task
    results = []
    for task in tasks[:5]:
        result = execute_code_task(task, chain_id=chain_id)
        results.append(result)
        if not result.get("success") and result.get("write_errors"):
            print(f"[CODE] Task failed, continuing: {task[:80]}", flush=True)

    all_written = []
    for r in results:
        all_written.extend(r.get("written_files", []))

    return {
        "success":       any(r.get("success") for r in results),
        "feature":       spec[:200],
        "tasks_executed": len(results),
        "written_files": all_written,
        "task_results":  results,
    }


# --------------------------------------------------
# CODE REVIEW
# --------------------------------------------------

def code_review(path: str) -> dict:
    content = read_existing(path)
    if not content:
        return {"error": f"Could not read: {path}"}

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior Python/JavaScript code reviewer. "
                "Be direct and specific. Focus on bugs, security issues, "
                "performance problems, and architectural concerns."
            )
        },
        {
            "role": "user",
            "content": f"""Review this code at {path}:

```
{content[:4000]}
```

Return findings as JSON:
{{
  "overall": "pass|needs_work|critical",
  "issues": [
    {{"severity": "critical|high|medium|low", "line": 0, "description": ""}}
  ],
  "recommendations": ["..."],
  "summary": "one sentence verdict"
}}"""
        }
    ]

    raw = call_llm(messages, role="code")
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(clean)
    except Exception:
        return {"raw_review": raw, "path": path}


# --------------------------------------------------
# CHAIN MODE INSTRUCTION (offer_stack)
# --------------------------------------------------

def build_code_instruction(executive: str, identity: str, soul: str, payload: dict) -> str:
    target  = payload.get("target", "")
    product = payload.get("product", "")
    upstream = payload.get("upstream_context", "")

    return f"""
=== EXECUTIVE STACK ===
{executive}

=== AGENT IDENTITY ===
{identity}

=== AGENT SOUL ===
{soul}

=== UPSTREAM CHAIN CONTEXT ===
{upstream}

Target: {target}
Product: {product}

You are the Code Agent. Based on the full chain output above:

1. Identify what code, tools, or systems need to be built
2. Generate complete, production-ready implementations
3. Write actual deployable files
4. Specify exactly which containers need restart after deployment
5. Include all imports, error handling, and integration points

Output format for each file:
FILE: /full/path/to/file.ext
```language
<complete implementation>
```

Then provide a deployment checklist.
""".strip()


# --------------------------------------------------
# PROCESS TASK
# --------------------------------------------------

def process_task(raw_envelope: Any) -> None:
    envelope = _as_dict(raw_envelope)

    if not isinstance(envelope, dict) or not envelope:
        print("[CODE] Skipping invalid envelope", flush=True)
        return

    doctrine  = _as_dict(envelope.get("doctrine"))
    executive = doctrine.get("executive", "")
    identity  = doctrine.get("identity", "")
    soul      = doctrine.get("soul", "")
    task_type = envelope.get("task_type")
    payload   = _as_dict(envelope.get("payload"))
    chain_id  = payload.get("chain_id")

    if not task_type:
        print("[CODE] Missing task_type", flush=True)
        return

    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[CODE] Stage already completed: {chain_id}", flush=True)
        return

    print(f"[CODE] Task: {task_type} | chain_id={chain_id}", flush=True)

    # ── CHAT PASSTHROUGH ────────────────────────────────────────────
    if task_type == "chat":
        msg = payload.get("message") or payload.get("product", "")
        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)
        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": "chat",
            "result": build_artifact("chat_echo", "1.0", {"text": f"[Code Agent] {msg}"}),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── CODE TASK ───────────────────────────────────────────────────
    if task_type == "code_task":
        task    = payload.get("task") or payload.get("message") or payload.get("instruction", "")
        context = payload.get("context", "")

        # Pull upstream context from memory if available
        if not context and chain_id and MCP_AVAILABLE:
            context = mcp("memory", "get_chain_summary", {"chain_id": chain_id}) or ""

        result = execute_code_task(task, context=context, chain_id=chain_id)

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("code_output", "1.0", result),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── BUILD FEATURE ───────────────────────────────────────────────
    if task_type == "build_feature":
        spec   = payload.get("spec") or payload.get("message") or payload.get("task", "")
        result = build_feature(spec, chain_id=chain_id)

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("feature_build", "1.0", result),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── CODE REVIEW ─────────────────────────────────────────────────
    if task_type == "code_review":
        path   = payload.get("path", "")
        result = code_review(path)

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("code_review", "1.0", result),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── OFFER STACK (chain mode) ─────────────────────────────────────
    if task_type == "offer_stack":
        upstream = payload.get("upstream_context", "")
        if not upstream and chain_id and MCP_AVAILABLE:
            upstream = mcp("memory", "get_chain_summary", {"chain_id": chain_id}) or ""

        instruction = build_code_instruction(executive, identity, soul, {**payload, "upstream_context": upstream})

        messages = [
            {"role": "system", "content": "You are the Code Agent. Write production code only."},
            {"role": "user",   "content": instruction}
        ]
        raw_output = call_llm(messages, role="code", max_tokens=4096)

        # Auto-write any FILE: blocks found in output
        file_writes  = extract_file_writes(raw_output)
        written_files = []
        for fw in file_writes:
            if write_file(fw["path"], fw["content"]):
                written_files.append(fw["path"])

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("code_strategy", "1.0", {
                "raw_output": raw_output,
                "written_files": written_files,
            }),
            "payload": payload, "doctrine": doctrine,
        })
        return

    print(f"[CODE] Unknown task type: {task_type}", flush=True)


# --------------------------------------------------
# MAIN LOOP
# --------------------------------------------------

def run() -> None:
    print("[CODE] Elite Code Agent online. (MCP-Enabled)", flush=True)

    while True:
        try:
            raw      = dequeue_blocking(QUEUE_NAME)
            envelope = _as_dict(raw)
            retry    = envelope.get("retry_count", 0)

            try:
                process_task(envelope)

            except Exception as error:
                retry += 1
                envelope["retry_count"] = retry
                tb = traceback.format_exc()
                print(f"[CODE ERROR] retry={retry} | {error}", flush=True)
                print(tb, flush=True)

                if retry < MAX_RETRIES:
                    enqueue(RETRY_QUEUE, envelope)
                else:
                    enqueue(DEAD_QUEUE, envelope)
                    enqueue("queue.orchestrator.results", {
                        "agent": AGENT_NAME,
                        "task_type": envelope.get("task_type"),
                        "result": build_artifact("error", "1.0", {
                            "error": str(error), "retry_count": retry
                        }),
                        "payload":  envelope.get("payload"),
                        "doctrine": envelope.get("doctrine"),
                        "status":   "failed",
                    })

        except Exception as queue_error:
            print(f"[CODE QUEUE ERROR] {queue_error}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    run()
