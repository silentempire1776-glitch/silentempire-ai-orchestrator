"""
TOOL EXECUTOR SERVICE
=====================
Listens on queue.tool.request and executes tool calls on behalf of agents.
"""

import os
import json
import subprocess
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import redis

REDIS_URL          = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")
TOOL_REQUEST_QUEUE = "queue.tool.request"
TOOL_RESULT_PFX    = "queue.tool.result."

BLOCKED_PATHS = ["/etc/shadow", "/root/.ssh/id_rsa"]
DESTRUCTIVE_PATTERNS = ["rm -rf", "docker system prune", "DROP TABLE", "mkfs"]

r = redis.from_url(REDIS_URL, decode_responses=True)

def is_blocked(path):
    return any(path.startswith(b) for b in BLOCKED_PATHS)

def is_destructive(cmd):
    return any(p in cmd for p in DESTRUCTIVE_PATTERNS)

def tool_bash(params):
    command = params.get("command", "")
    timeout = int(params.get("timeout", 30))
    cwd     = params.get("cwd", "/srv/silentempire")
    force   = params.get("force", False)
    if not force and is_destructive(command):
        return {"success": False, "error": "Destructive command blocked. Pass force=true to override."}
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return {"success": result.returncode == 0, "stdout": result.stdout[-4000:], "stderr": result.stderr[-2000:], "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_file_read(params):
    path = params.get("path", "")
    if is_blocked(path):
        return {"success": False, "error": "Path blocked"}
    try:
        return {"success": True, "content": Path(path).read_text(encoding="utf-8", errors="replace")[:50000]}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_file_write(params):
    path    = params.get("path", "")
    content = params.get("content", "")
    if is_blocked(path):
        return {"success": False, "error": "Path blocked"}
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "bytes_written": len(content.encode())}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_file_list(params):
    path  = params.get("path", "/srv/silentempire")
    depth = int(params.get("depth", 1))
    try:
        base  = Path(path)
        items = base.rglob("*") if depth > 1 else base.iterdir()
        entries = []
        for item in sorted(items):
            rel = str(item.relative_to(base))
            if item.is_dir():
                rel += "/"
            entries.append(rel)
        return {"success": True, "entries": entries[:200]}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_docker_ps(params):
    result = subprocess.run("docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}'", shell=True, capture_output=True, text=True, timeout=10)
    containers = []
    for line in result.stdout.strip().split("\n"):
        parts = line.strip().split("\t")
        if len(parts) >= 3:
            containers.append({"name": parts[0], "status": parts[1], "image": parts[2]})
    return {"success": True, "containers": containers}

def tool_docker_logs(params):
    container = params.get("container", "")
    lines     = int(params.get("lines", 50))
    result    = subprocess.run(f"docker logs --tail {lines} {container} 2>&1", shell=True, capture_output=True, text=True, timeout=15)
    return {"success": True, "logs": result.stdout[-8000:]}

def tool_docker_restart(params):
    container = params.get("container", "")
    result    = subprocess.run(f"docker restart {container}", shell=True, capture_output=True, text=True, timeout=30)
    return {"success": result.returncode == 0, "output": result.stdout + result.stderr}

def tool_docker_exec(params):
    container = params.get("container", "")
    command   = params.get("command", "")
    result    = subprocess.run(f"docker exec {container} {command}", shell=True, capture_output=True, text=True, timeout=30)
    return {"success": result.returncode == 0, "stdout": result.stdout[-4000:], "stderr": result.stderr[-2000:], "returncode": result.returncode}

TOOLS = {
    "bash":           tool_bash,
    "file_read":      tool_file_read,
    "file_write":     tool_file_write,
    "file_list":      tool_file_list,
    "docker_ps":      tool_docker_ps,
    "docker_logs":    tool_docker_logs,
    "docker_restart": tool_docker_restart,
    "docker_exec":    tool_docker_exec,
}

def run():
    print(f"[TOOL EXECUTOR] Online — listening on {TOOL_REQUEST_QUEUE}", flush=True)
    print(f"[TOOL EXECUTOR] REDIS_URL={REDIS_URL}", flush=True)
    while True:
        try:
            item = r.brpop(TOOL_REQUEST_QUEUE, timeout=5)
            if not item:
                continue
            _, raw   = item
            request  = json.loads(raw)
            req_id   = request.get("request_id", str(uuid.uuid4()))
            tool     = request.get("tool", "")
            params   = request.get("params", {})
            reply_q  = request.get("reply_queue", f"{TOOL_RESULT_PFX}{req_id}")
            print(f"[TOOL EXECUTOR] request_id={req_id} tool={tool}", flush=True)
            if tool not in TOOLS:
                result = {"success": False, "error": f"Unknown tool: {tool}"}
            else:
                try:
                    result = TOOLS[tool](params)
                except Exception as e:
                    result = {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            result["request_id"]  = req_id
            result["tool"]        = tool
            result["executed_at"] = datetime.utcnow().isoformat()
            r.lpush(reply_q, json.dumps(result))
            r.expire(reply_q, 300)
            print(f"[TOOL EXECUTOR] Done request_id={req_id} success={result.get('success')}", flush=True)
        except Exception as e:
            print(f"[TOOL EXECUTOR] Loop error: {e}", flush=True)
            traceback.print_exc()

if __name__ == "__main__":
    run()
