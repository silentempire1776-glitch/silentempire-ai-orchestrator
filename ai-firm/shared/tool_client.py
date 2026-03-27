"""
TOOL CLIENT
===========
Used by any agent to call the tool_executor service.
Provides a clean interface: call_tool(tool, params) → result dict

Usage from any agent:
    from shared.tool_client import call_tool

    result = call_tool("bash", {"command": "docker ps"})
    if result["success"]:
        print(result["stdout"])

    result = call_tool("file_read", {"path": "/srv/silentempire/ai-firm/orchestrator/main.py"})
    result = call_tool("file_write", {"path": "/tmp/test.txt", "content": "hello"})
    result = call_tool("docker_logs", {"container": "jarvis-orchestrator", "lines": 100})
"""

import os
import json
import uuid
import time
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
TOOL_REQUEST_QUEUE = "queue.tool.request"
TOOL_RESULT_QUEUE_PREFIX = "queue.tool.result."

_r = redis.from_url(REDIS_URL, decode_responses=True)


def call_tool(tool: str, params: dict, timeout: int = 60) -> dict:
    """
    Submit a tool call to the executor and wait for result.

    Args:
        tool: one of bash, file_read, file_write, file_list,
              docker_ps, docker_logs, docker_restart, docker_exec
        params: dict of tool-specific parameters
        timeout: seconds to wait for result

    Returns:
        dict with at minimum: {"success": bool, ...tool output...}
    """
    request_id = str(uuid.uuid4())
    reply_queue = f"{TOOL_RESULT_QUEUE_PREFIX}{request_id}"

    request = {
        "request_id": request_id,
        "tool": tool,
        "params": params,
        "reply_queue": reply_queue
    }

    _r.lpush(TOOL_REQUEST_QUEUE, json.dumps(request))

    # Wait for result
    item = _r.brpop(reply_queue, timeout=timeout)
    if not item:
        return {"success": False, "error": f"Tool call timed out after {timeout}s"}

    _, raw = item
    return json.loads(raw)
