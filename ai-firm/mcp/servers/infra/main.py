"""
=========================================================
MCP Infra Server — Silent Empire
Self-modification and infrastructure control.
Wraps your existing tool-executor with MCP interface.

Tools:
  bash(command, timeout?)             → {stdout, stderr, exit_code}
  docker_ps()                         → [{name, status, image}]
  docker_restart(container)           → {status}
  docker_logs(container, lines?)      → str
  docker_rebuild(service, path?)      → {status}
  write_and_deploy(path, content, service) → {status}
  git_pull(path?)                     → {status, output}
  get_system_health()                 → {containers, disk, memory}
=========================================================
"""

import os
import sys
import json
import subprocess
import time
from typing import Any

sys.path.insert(0, "/ai-firm")

from mcp.shared.mcp_protocol import MCPServer

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "false").lower() == "true"
SILENTEMPIRE_ROOT = "/srv/silentempire"

# Commands that are never allowed regardless of approval setting
BLOCKED_COMMANDS = [
    "rm -rf /",
    "dd if=",
    "mkfs",
    "shutdown",
    "reboot",
    "> /dev/sd",
]


def _is_blocked(command: str) -> bool:
    cmd_lower = command.lower().strip()
    return any(b in cmd_lower for b in BLOCKED_COMMANDS)


# --------------------------------------------------
# TOOL IMPLEMENTATIONS
# --------------------------------------------------

def tool_bash(params: dict) -> dict:
    command = params.get("command", "").strip()
    timeout = int(params.get("timeout", 30))

    if not command:
        raise ValueError("command required")

    if _is_blocked(command):
        raise PermissionError(f"Command blocked by safety policy: {command}")

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=SILENTEMPIRE_ROOT,
        )
        return {
            "stdout": result.stdout[-4000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "exit_code": result.returncode,
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1,
            "command": command,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -2,
            "command": command,
        }


def tool_docker_ps(params: dict) -> list:
    result = tool_bash({
        "command": "docker ps --format '{{json .}}' 2>&1",
        "timeout": 10
    })

    containers = []
    for line in result["stdout"].strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except Exception:
            continue

    return containers


def tool_docker_restart(params: dict) -> dict:
    container = params.get("container", "").strip()
    if not container:
        raise ValueError("container required")

    result = tool_bash({
        "command": f"docker restart {container}",
        "timeout": 30
    })

    return {
        "status": "restarted" if result["exit_code"] == 0 else "failed",
        "container": container,
        "output": result["stdout"] or result["stderr"],
    }


def tool_docker_logs(params: dict) -> str:
    container = params.get("container", "").strip()
    lines     = int(params.get("lines", 100))

    if not container:
        raise ValueError("container required")

    result = tool_bash({
        "command": f"docker logs --tail {lines} {container} 2>&1",
        "timeout": 10
    })

    return result["stdout"] or result["stderr"]


def tool_docker_rebuild(params: dict) -> dict:
    """
    Rebuild and restart a service.
    Used by Systems agent for self-modification deployments.
    """
    service = params.get("service", "").strip()
    path    = params.get("path", "").strip() or SILENTEMPIRE_ROOT

    if not service:
        raise ValueError("service required")

    # Map service names to their compose directories
    compose_dirs = {
        "api":         f"{SILENTEMPIRE_ROOT}/app",
        "worker":      f"{SILENTEMPIRE_ROOT}/app",
        "jarvis":      f"{SILENTEMPIRE_ROOT}/ai-firm",
        "research":    f"{SILENTEMPIRE_ROOT}/ai-firm",
        "revenue":     f"{SILENTEMPIRE_ROOT}/ai-firm",
        "sales":       f"{SILENTEMPIRE_ROOT}/ai-firm",
        "growth":      f"{SILENTEMPIRE_ROOT}/ai-firm",
        "product":     f"{SILENTEMPIRE_ROOT}/ai-firm",
        "legal":       f"{SILENTEMPIRE_ROOT}/ai-firm",
        "systems":     f"{SILENTEMPIRE_ROOT}/ai-firm",
        "mission-control": f"{SILENTEMPIRE_ROOT}/app",
    }

    compose_dir = compose_dirs.get(service, path)

    result = tool_bash({
        "command": f"cd {compose_dir} && docker compose up -d --build {service} 2>&1",
        "timeout": 120,
    })

    return {
        "status": "rebuilt" if result["exit_code"] == 0 else "failed",
        "service": service,
        "output": (result["stdout"] or result["stderr"])[-2000:],
    }


def tool_write_and_deploy(params: dict) -> dict:
    """
    Write a file and optionally restart/rebuild a service.
    The core self-modification tool.
    """
    path    = params.get("path", "").strip()
    content = params.get("content", "")
    service = params.get("service", "")

    if not path:
        raise ValueError("path required")

    # Security: only write within silentempire root
    real_path = os.path.realpath(path)
    if not real_path.startswith(SILENTEMPIRE_ROOT):
        raise PermissionError(f"Write blocked: {path}")

    os.makedirs(os.path.dirname(real_path), exist_ok=True)
    with open(real_path, "w") as f:
        f.write(content)

    result = {"status": "written", "path": real_path}

    # Optionally restart a service after writing
    if service:
        restart = tool_docker_restart({"container": service})
        result["restart"] = restart

    return result


def tool_git_pull(params: dict) -> dict:
    path = params.get("path", SILENTEMPIRE_ROOT)

    result = tool_bash({
        "command": f"cd {path} && git pull 2>&1",
        "timeout": 30
    })

    return {
        "status": "ok" if result["exit_code"] == 0 else "failed",
        "output": result["stdout"] or result["stderr"],
    }


def tool_get_system_health(params: dict) -> dict:
    """
    Returns a health snapshot: container statuses, disk, memory.
    Used by Jarvis for autonomous health checks.
    """
    containers = tool_docker_ps({})

    disk_result = tool_bash({"command": "df -h / 2>&1", "timeout": 5})
    mem_result  = tool_bash({"command": "free -h 2>&1",  "timeout": 5})
    load_result = tool_bash({"command": "uptime 2>&1",   "timeout": 5})

    container_summary = [
        {
            "name": c.get("Names", "?"),
            "status": c.get("Status", "?"),
            "image": c.get("Image", "?"),
        }
        for c in containers
    ]

    return {
        "containers": container_summary,
        "container_count": len(container_summary),
        "disk": disk_result["stdout"].strip(),
        "memory": mem_result["stdout"].strip(),
        "load": load_result["stdout"].strip(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# --------------------------------------------------
# SERVER ASSEMBLY
# --------------------------------------------------

class InfraServer(MCPServer):
    def __init__(self):
        super().__init__("infra")
        self.register_tool("bash",              tool_bash)
        self.register_tool("docker_ps",         tool_docker_ps)
        self.register_tool("docker_restart",    tool_docker_restart)
        self.register_tool("docker_logs",       tool_docker_logs)
        self.register_tool("docker_rebuild",    tool_docker_rebuild)
        self.register_tool("write_and_deploy",  tool_write_and_deploy)
        self.register_tool("git_pull",          tool_git_pull)
        self.register_tool("get_system_health", tool_get_system_health)


if __name__ == "__main__":
    server = InfraServer()
    server.run()
