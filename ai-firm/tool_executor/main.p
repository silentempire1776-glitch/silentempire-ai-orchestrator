"""
TOOL EXECUTOR SERVICE
=====================
Purpose: Secure command execution sidecar for the Silent Empire agent system.
         Agents submit tool_call requests to Redis queue.
         This service executes them and returns results.

Supported tools:
  - bash: run shell commands on the VPS host (via Docker socket or direct)
  - file_read: read any file path
  - file_write: write/create files
  - file_list: list directory contents
  - docker_ps: list running containers
  - docker_logs: get container logs
  - docker_restart: restart a container
  - docker_exec: run command inside a container

Security model:
  - BLOCKED_PATHS: list of paths that cannot be read/written
  - ALLOWED_COMMANDS: optional allowlist for bash
  - REQUIRE_APPROVAL: sends to Telegram before executing destructive ops
"""

import os
import json
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
import redis

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
TOOL_REQUEST_QUEUE = "queue.tool.request"
TOOL_RESULT_QUEUE_PREFIX = "queue.tool.result."  # + request_id

# Paths that can NEVER be read or written
BLOCKED_PATHS = [
    "/etc/shadow",
    "/root/.ssh/id_rsa",
    "/srv/silentempire/app/.env",
]

# Commands that require human approval (Telegram)
DESTRUCTIVE_PATTERNS = [
    "rm -rf",
    "docker system prune",
    "DROP TABLE",
    "format",
    "mkfs",
]

APPROVAL_REQUIRED = os.getenv("REQUIRE_APPROVAL", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --------------------------------------------------
# REDIS
# --------------------------------------------------

r = redis.from_url(REDIS_URL, decode_responses=True)

# --------------------------------------------------
# SECURITY CHECKS
# --------------------------------------------------

def is_blocked_path(path: str) -> bool:
    for blocked in BLOCKED_PATHS:
        if path.startswith(blocked):
            return True
    return False

def is_destructive(command: str) -> bool:
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern in command:
            return True
    return False

def send_telegram_approval(request_id: str, tool: str, params: dict) -> bool:
    """Send approval request to Telegram. Returns True if approved."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return True  # No Telegram configured = auto-approve
    
    import requests as req
    msg = (
        f"⚠️ APPROVAL REQUIRED\n"
        f"Request ID: {request_id}\n"
        f"Tool: {tool}\n"
        f"Params: {json.dumps(params, indent=2)[:500]}\n\n"
        f"Reply with: APPROVE {request_id} or DENY {request_id}"
    )
    req.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
        timeout=5
    )
    
    # Poll for approval (60s timeout)
    approval_key = f"tool.approval.{request_id}"
    import time
    for _ in range(60):
        val = r.get(approval_key)
        if val == "APPROVED":
            return True
        if val == "DENIED":
            return False
        time.sleep(1)
    return False  # Timeout = deny

# --------------------------------------------------
# TOOL HANDLERS
# --------------------------------------------------

def tool_bash(params: dict) -> dict:
    command = params.get("command", "")
    timeout = int(params.get("timeout", 30))
    working_dir = params.get("cwd", "/srv/silentempire")
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir
        )
        return {
            "stdout": result.stdout[-4000:],  # last 4k chars
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def tool_file_read(params: dict) -> dict:
    path = params.get("path", "")
    if is_blocked_path(path):
        return {"error": "Path is blocked by security policy", "success": False}
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return {"content": content[:50000], "success": True}  # 50k char limit
    except Exception as e:
        return {"error": str(e), "success": False}


def tool_file_write(params: dict) -> dict:
    path = params.get("path", "")
    content = params.get("content", "")
    if is_blocked_path(path):
        return {"error": "Path is blocked by security policy", "success": False}
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "bytes_written": len(content.encode())}
    except Exception as e:
        return {"error": str(e), "success": False}


def tool_file_list(params: dict) -> dict:
    path = params.get("path", "/srv/silentempire")
    depth = int(params.get("depth", 1))
    try:
        entries = []
        base = Path(path)
        for item in sorted(base.rglob("*") if depth > 1 else base.iterdir()):
            try:
                rel = str(item.relative_to(base))
                if item.is_dir():
                    rel += "/"
                entries.append(rel)
            except Exception:
                pass
        return {"entries": entries[:200], "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def tool_docker_ps(params: dict) -> dict:
    result = subprocess.run(
        "docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}'",
        shell=True, capture_output=True, text=True, timeout=10
    )
    lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
    containers = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 3:
            containers.append({"name": parts[0], "status": parts[1], "image": parts[2]})
    return {"containers": containers, "success": True}


def tool_docker_logs(params: dict) -> dict:
    container = params.get("container", "")
    lines = int(params.get("lines", 50))
    result = subprocess.run(
        f"docker logs --tail {lines} {container} 2>&1",
        shell=True, capture_output=True, text=True, timeout=15
    )
    return {"logs": result.stdout[-8000:], "success": True}


def tool_docker_restart(params: dict) -> dict:
    container = params.get("container", "")
    result = subprocess.run(
        f"docker restart {container}",
        shell=True, capture_output=True, text=True, timeout=30
    )
    return {
        "success": result.returncode == 0,
        "output": result.stdout + result.stderr
    }


def tool_docker_exec(params: dict) -> dict:
    container = params.get("container", "")
    command = params.get("command", "")
    result = subprocess.run(
        f"docker exec {container} {command}",
        shell=True, capture_output=True, text=True, timeout=30
    )
    return {
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-2000:],
        "returncode": result.returncode,
        "success": result.returncode == 0
    }


# --------------------------------------------------
# TOOL REGISTRY
# --------------------------------------------------

TOOLS = {
    "bash": tool_bash,
    "file_read": tool_file_read,
    "file_write": tool_file_write,
    "file_list": tool_file_list,
    "docker_ps": tool_docker_ps,
    "docker_logs": tool_docker_logs,
    "docker_restart": tool_docker_restart,
    "docker_exec": tool_docker_exec,
}

# --------------------------------------------------
# MAIN LOOP
# --------------------------------------------------

def run():
    print("[TOOL EXECUTOR] Online. Listening on queue.tool.request", flush=True)
    while True:
        try:
            item = r.brpop(TOOL_REQUEST_QUEUE, timeout=5)
            if not item:
                continue
            
            _, raw = item
            request = json.loads(raw)
            
            request_id = request.get("request_id", "unknown")
            tool = request.get("tool", "")
            params = request.get("params", {})
            reply_queue = request.get("reply_queue", f"{TOOL_RESULT_QUEUE_PREFIX}{request_id}")
            
            print(f"[TOOL EXECUTOR] Request: {request_id} tool={tool}", flush=True)
            
            # Security: check destructive
            if tool == "bash" and is_destructive(params.get("command", "")):
                if APPROVAL_REQUIRED:
                    approved = send_telegram_approval(request_id, tool, params)
                    if not approved:
                        result = {"error": "Denied by approval gate", "success": False}
                        r.lpush(reply_queue, json.dumps(result))
                        r.expire(reply_queue, 300)
                        continue
            
            # Execute tool
            if tool not in TOOLS:
                result = {"error": f"Unknown tool: {tool}", "success": False}
            else:
                try:
                    result = TOOLS[tool](params)
                except Exception as e:
                    result = {"error": str(e), "traceback": traceback.format_exc(), "success": False}
            
            result["request_id"] = request_id
            result["tool"] = tool
            result["executed_at"] = datetime.utcnow().isoformat()
            
            r.lpush(reply_queue, json.dumps(result))
            r.expire(reply_queue, 300)  # 5 min TTL
            
            print(f"[TOOL EXECUTOR] Done: {request_id} success={result.get('success')}", flush=True)
            
        except Exception as e:
            print(f"[TOOL EXECUTOR] Error: {e}", flush=True)
            traceback.print_exc()


if __name__ == "__main__":
    run()
