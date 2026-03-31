"""
=========================================================
MCP Memory Server — Silent Empire
Context store that eliminates prompt bloat.

Instead of injecting full chain history into every LLM call,
agents call this server to get only what they need.

Tools:
  get_context(chain_id, key?)        → dict
  set_context(chain_id, key, value)  → ok
  get_agent_memory(agent, key)       → value
  set_agent_memory(agent, key, value)→ ok
  get_doctrine(agent_name)           → str
  get_chain_summary(chain_id)        → str (compressed)
  store_result(chain_id, agent, data)→ ok
  get_result(chain_id, agent)        → dict
=========================================================
"""

import os
import json
import hashlib
import psycopg2
import redis
from datetime import datetime
from typing import Any, Optional

# Add shared path
import sys
sys.path.insert(0, "/ai-firm")

from mcp.shared.mcp_protocol import MCPServer

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL    = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")
DOCTRINE_PATH = "/ai-firm/shared/doctrine"

_r = redis.from_url(REDIS_URL, decode_responses=True)

# Redis key TTL for context (24 hours)
CONTEXT_TTL = 86400

# --------------------------------------------------
# POSTGRES HELPERS
# --------------------------------------------------

def _pg():
    return psycopg2.connect(DATABASE_URL)


def _init_memory_tables():
    conn = _pg()
    cur = conn.cursor()

    # Long-term agent memory (survives restarts)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_memory (
            id SERIAL PRIMARY KEY,
            agent TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(agent, key)
        )
    """)

    # Chain context snapshots (compressed per-chain results)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chain_context (
            id SERIAL PRIMARY KEY,
            chain_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            result_summary TEXT,
            full_result JSONB,
            token_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(chain_id, agent)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("[MCP:memory] Tables initialized", flush=True)


# --------------------------------------------------
# DOCTRINE CACHE (loaded once, hashed for change detection)
# --------------------------------------------------

_doctrine_cache: dict = {}
_doctrine_hashes: dict = {}


def _load_doctrine_file(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""


def _get_doctrine(agent_name: str) -> str:
    """
    Returns concatenated doctrine for an agent.
    Uses Redis cache with hash-based invalidation.
    """
    cache_key = f"doctrine:{agent_name}"

    # Check Redis cache first
    cached = _r.get(cache_key)
    if cached:
        return cached

    # Build from files
    parts = []

    executive = _load_doctrine_file(f"{DOCTRINE_PATH}/EXECUTIVE_STACK.md")
    if executive:
        parts.append(f"=== EXECUTIVE STACK ===\n{executive}")

    identity = _load_doctrine_file(f"/ai-firm/agents/{agent_name}/IDENTITY.md")
    if identity:
        parts.append(f"=== IDENTITY ===\n{identity}")

    soul = _load_doctrine_file(f"/ai-firm/agents/{agent_name}/SOUL.md")
    if soul:
        parts.append(f"=== SOUL ===\n{soul}")

    combined = "\n\n".join(parts)

    # Cache for 10 minutes
    _r.setex(cache_key, 600, combined)

    return combined


# --------------------------------------------------
# CONTEXT COMPRESSION
# Reduces agent output to ~200 tokens for passing
# downstream instead of full JSON artifacts.
# --------------------------------------------------

def _compress_result(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data[:1200]  # ~300 tokens max
    if isinstance(data, dict):
        # Pull the highest-signal fields
        priority_keys = [
            "market_landscape", "competitive_positioning", "demand_signals",
            "offer_architecture", "primary_channels", "positioning_statement",
            "revenue_model", "risk_factors", "key_insights", "synthesis",
            "raw_output", "output", "result"
        ]
        parts = []
        for k in priority_keys:
            v = data.get(k)
            if v:
                if isinstance(v, list):
                    v = ", ".join(str(i) for i in v[:3])
                parts.append(f"{k}: {str(v)[:200]}")
        if parts:
            return " | ".join(parts)[:1200]
        # fallback: first 1200 chars of JSON
        return json.dumps(data)[:1200]
    return str(data)[:1200]


# --------------------------------------------------
# TOOL IMPLEMENTATIONS
# --------------------------------------------------

def tool_get_context(params: dict) -> dict:
    """
    Returns all stored context for a chain_id.
    Agents call this instead of receiving full chain state in prompt.
    """
    chain_id = params.get("chain_id")
    if not chain_id:
        return {}

    # Check Redis first (hot cache)
    cache_key = f"ctx:{chain_id}"
    cached = _r.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    # Fallback to Postgres
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("""
            SELECT agent, result_summary, full_result
            FROM chain_context
            WHERE chain_id = %s
            ORDER BY created_at ASC
        """, (chain_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        context = {}
        for agent, summary, full in rows:
            context[agent] = {
                "summary": summary,
                "full": full
            }
        return context
    except Exception as e:
        print(f"[MCP:memory] get_context error: {e}", flush=True)
        return {}


def tool_set_context(params: dict) -> str:
    chain_id = params.get("chain_id")
    key      = params.get("key", "misc")
    value    = params.get("value")

    if not chain_id:
        return "error: missing chain_id"

    # Update Redis hot cache
    cache_key = f"ctx:{chain_id}"
    existing_raw = _r.get(cache_key)
    existing = {}
    if existing_raw:
        try:
            existing = json.loads(existing_raw)
        except Exception:
            pass

    existing[key] = value
    _r.setex(cache_key, CONTEXT_TTL, json.dumps(existing))
    return "ok"


def tool_store_result(params: dict) -> str:
    """
    Stores a full agent result AND compressed summary.
    Called after each agent completes.
    """
    chain_id = params.get("chain_id")
    agent    = params.get("agent")
    data     = params.get("data")

    if not chain_id or not agent:
        return "error: missing chain_id or agent"

    summary = _compress_result(data)

    # Write to Postgres
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO chain_context (chain_id, agent, result_summary, full_result)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chain_id, agent)
            DO UPDATE SET
                result_summary = EXCLUDED.result_summary,
                full_result = EXCLUDED.full_result
        """, (chain_id, agent, summary, json.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[MCP:memory] store_result pg error: {e}", flush=True)

    # Update Redis cache
    cache_key = f"ctx:{chain_id}"
    existing_raw = _r.get(cache_key)
    existing = {}
    if existing_raw:
        try:
            existing = json.loads(existing_raw)
        except Exception:
            pass

    existing[agent] = {"summary": summary, "full": data}
    _r.setex(cache_key, CONTEXT_TTL, json.dumps(existing))

    return "ok"


def tool_get_result(params: dict) -> dict:
    chain_id = params.get("chain_id")
    agent    = params.get("agent")

    if not chain_id or not agent:
        return {}

    # Redis first
    cache_key = f"ctx:{chain_id}"
    cached = _r.get(cache_key)
    if cached:
        try:
            ctx = json.loads(cached)
            if agent in ctx:
                return ctx[agent]
        except Exception:
            pass

    # Postgres fallback
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("""
            SELECT result_summary, full_result
            FROM chain_context
            WHERE chain_id = %s AND agent = %s
        """, (chain_id, agent))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {"summary": row[0], "full": row[1]}
    except Exception as e:
        print(f"[MCP:memory] get_result error: {e}", flush=True)

    return {}


def tool_get_agent_memory(params: dict) -> str:
    agent = params.get("agent")
    key   = params.get("key")
    if not agent or not key:
        return ""

    # Redis cache
    rk = f"agentmem:{agent}:{key}"
    cached = _r.get(rk)
    if cached:
        return cached

    # Postgres
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("""
            SELECT value FROM agent_memory WHERE agent = %s AND key = %s
        """, (agent, key))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            _r.setex(rk, CONTEXT_TTL, row[0])
            return row[0]
    except Exception as e:
        print(f"[MCP:memory] get_agent_memory error: {e}", flush=True)

    return ""


def tool_set_agent_memory(params: dict) -> str:
    agent = params.get("agent")
    key   = params.get("key")
    value = params.get("value", "")

    if not agent or not key:
        return "error: missing agent or key"

    # Redis
    rk = f"agentmem:{agent}:{key}"
    _r.setex(rk, CONTEXT_TTL * 30, str(value))  # 30-day TTL for long-term memory

    # Postgres
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO agent_memory (agent, key, value, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (agent, key)
            DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, (agent, key, str(value)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[MCP:memory] set_agent_memory error: {e}", flush=True)

    return "ok"


def tool_get_doctrine(params: dict) -> str:
    agent_name = params.get("agent", "")
    return _get_doctrine(agent_name)


def tool_get_chain_summary(params: dict) -> str:
    """
    Returns a compressed multi-agent summary for passing to downstream agents.
    This replaces full artifact injection — ~90% token reduction.
    """
    chain_id = params.get("chain_id")
    agents   = params.get("agents", [])  # if empty, returns all agents

    if not chain_id:
        return ""

    ctx = tool_get_context({"chain_id": chain_id})
    if not ctx:
        return ""

    lines = []
    for agent, data in ctx.items():
        if agents and agent not in agents:
            continue
        summary = data.get("summary") if isinstance(data, dict) else str(data)
        if summary:
            lines.append(f"[{agent.upper()}] {summary}")

    return "\n".join(lines)[:2000]  # hard cap ~500 tokens


# --------------------------------------------------
# SERVER ASSEMBLY
# --------------------------------------------------

class MemoryServer(MCPServer):
    def __init__(self):
        super().__init__("memory")
        self.register_tool("get_context",       tool_get_context)
        self.register_tool("set_context",       tool_set_context)
        self.register_tool("store_result",      tool_store_result)
        self.register_tool("get_result",        tool_get_result)
        self.register_tool("get_agent_memory",  tool_get_agent_memory)
        self.register_tool("set_agent_memory",  tool_set_agent_memory)
        self.register_tool("get_doctrine",      tool_get_doctrine)
        self.register_tool("get_chain_summary", tool_get_chain_summary)


if __name__ == "__main__":
    _init_memory_tables()
    server = MemoryServer()
    server.run()
