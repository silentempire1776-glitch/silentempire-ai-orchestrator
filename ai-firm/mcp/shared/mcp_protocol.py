"""
=========================================================
Silent Empire MCP Protocol — Elite Transport Layer
JSON-RPC 2.0 over Redis
=========================================================

All MCP servers and the Jarvis client use this module.
- Server: registers tools, listens on queue.mcp.<server_name>
- Client: calls tools, waits for response on queue.mcp.reply.<request_id>
"""

import json
import uuid
import time
import os
from typing import Any, Callable, Dict, Optional

import redis

# --------------------------------------------------
# REDIS
# --------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")
_r = redis.from_url(REDIS_URL, decode_responses=True)

MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "60"))   # seconds per tool call
MCP_PREFIX   = "queue.mcp"


# --------------------------------------------------
# MCP REQUEST / RESPONSE ENVELOPE
# --------------------------------------------------

def make_request(server: str, tool: str, params: dict, request_id: str = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "method": tool,
        "params": params,
        "server": server,
    }


def make_response(request_id: str, result: Any = None, error: str = None) -> dict:
    resp = {"jsonrpc": "2.0", "id": request_id}
    if error:
        resp["error"] = {"message": error}
    else:
        resp["result"] = result
    return resp


# --------------------------------------------------
# CLIENT — synchronous call_tool
# Jarvis uses this to call any MCP server tool.
# --------------------------------------------------

class MCPClient:
    """
    Synchronous MCP client.
    Usage:
        client = MCPClient()
        result = client.call_tool("memory", "get_context", {"chain_id": "abc"})
    """

    def __init__(self):
        self.r = _r

    def call_tool(self, server: str, tool: str, params: dict, timeout: int = MCP_TIMEOUT) -> Any:
        request_id = str(uuid.uuid4())
        request = make_request(server, tool, params, request_id)

        # Reply queue is unique per call — no cross-contamination
        reply_queue = f"{MCP_PREFIX}.reply.{request_id}"

        # Push request to server queue
        server_queue = f"{MCP_PREFIX}.{server}"
        self.r.lpush(server_queue, json.dumps(request))

        # Block-wait for response
        result = self.r.brpop(reply_queue, timeout=timeout)
        if result is None:
            raise TimeoutError(f"MCP call timed out: server={server} tool={tool} id={request_id}")

        _, raw = result
        response = json.loads(raw)

        if "error" in response and response["error"]:
            raise RuntimeError(f"MCP server error [{server}.{tool}]: {response['error']['message']}")

        return response.get("result")


# --------------------------------------------------
# SERVER — base class for all MCP servers
# --------------------------------------------------

class MCPServer:
    """
    Base MCP server.
    Subclass and register tools with @self.tool(name).

    Usage:
        class MemoryServer(MCPServer):
            def __init__(self):
                super().__init__("memory")
                self.register_tool("get_context", self.get_context)
                self.register_tool("set_context", self.set_context)

            def get_context(self, params):
                ...

        server = MemoryServer()
        server.run()
    """

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.queue = f"{MCP_PREFIX}.{server_name}"
        self.tools: Dict[str, Callable] = {}
        self.r = _r
        print(f"[MCP:{server_name}] Server initialized. Queue: {self.queue}", flush=True)

    def register_tool(self, name: str, fn: Callable):
        self.tools[name] = fn
        print(f"[MCP:{self.server_name}] Tool registered: {name}", flush=True)

    def _dispatch(self, raw: str):
        try:
            request = json.loads(raw)
        except Exception as e:
            print(f"[MCP:{self.server_name}] Invalid JSON: {e}", flush=True)
            return

        request_id = request.get("id")
        method     = request.get("method")
        params     = request.get("params", {})
        reply_q    = f"{MCP_PREFIX}.reply.{request_id}"

        if method not in self.tools:
            resp = make_response(request_id, error=f"Unknown tool: {method}")
            self.r.lpush(reply_q, json.dumps(resp))
            self.r.expire(reply_q, 120)
            return

        try:
            result = self.tools[method](params)
            resp = make_response(request_id, result=result)
        except Exception as e:
            print(f"[MCP:{self.server_name}] Tool error [{method}]: {e}", flush=True)
            resp = make_response(request_id, error=str(e))

        # Push response; expires in 2 min to clean up if caller died
        self.r.lpush(reply_q, json.dumps(resp))
        self.r.expire(reply_q, 120)

    def run(self):
        print(f"[MCP:{self.server_name}] Online. Listening on {self.queue}", flush=True)
        while True:
            try:
                item = self.r.brpop(self.queue, timeout=5)
                if item:
                    _, raw = item
                    self._dispatch(raw)
            except Exception as e:
                print(f"[MCP:{self.server_name}] Loop error: {e}", flush=True)
                time.sleep(1)
