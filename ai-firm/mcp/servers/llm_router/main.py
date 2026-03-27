"""
=========================================================
MCP LLM Router Server — Silent Empire
Centralizes ALL LLM execution.

Agents no longer call /jobs directly.
They call this MCP server with (model, messages, budget_tier).
The server handles: provider selection, cost tracking, fallback,
token counting, and response streaming back to caller.

Tools:
  run(model, messages, budget_tier?, timeout?)  → {content, tokens, cost, model, provider}
  get_model_for_role(role)                      → model_id string
  get_usage_today()                             → {cost_usd, tokens}
  list_models()                                 → [{id, provider, cost_per_1k}]
=========================================================
"""

import os
import sys
import json
import time
import requests
from typing import Any, Optional

sys.path.insert(0, "/ai-firm")
sys.path.insert(0, "/app")

from mcp.shared.mcp_protocol import MCPServer

import psycopg2
import redis

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL    = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")
NVIDIA_KEY   = os.getenv("NVIDIA_API_KEY") or os.getenv("MOONSHOT_API_KEY")
NVIDIA_BASE  = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
OPENAI_KEY   = os.getenv("OPENAI_API_KEY")
FORCE_FREE   = os.getenv("FORCE_FREE_MODE", "false").lower() == "true"

_r = redis.from_url(REDIS_URL, decode_responses=True)


# --------------------------------------------------
# ROLE → MODEL MAP (env-driven, matches your worker)
# --------------------------------------------------

ROLE_MODEL_MAP = {
    "research":           os.getenv("MODEL_RESEARCH",          "moonshotai/kimi-k2.5"),
    "revenue":            os.getenv("MODEL_REVENUE",           "qwen/qwen3.5-397b-a17b"),
    "sales":              os.getenv("MODEL_SALES",             "qwen/qwen3.5-122b-a10b"),
    "growth":             os.getenv("MODEL_GROWTH",            "qwen/qwen3.5-397b-a17b"),
    "product":            os.getenv("MODEL_PRODUCT",           "qwen/qwen3.5-397b-a17b"),
    "legal":              os.getenv("MODEL_LEGAL",             "qwen/qwen3.5-397b-a17b"),
    "systems":            os.getenv("MODEL_SYSTEMS",           "qwen/qwen3.5-122b-a10b"),
    "code":               os.getenv("MODEL_CODING",            "qwen/qwen3.5-122b-a10b"),
    "voice":              os.getenv("MODEL_VOICE",             "meta/llama-4-maverick-17b-128e-instruct"),
    "fast":               os.getenv("MODEL_FAST_WORKER",       "meta/llama-4-scout-17b-16e-instruct"),
    "jarvis":             os.getenv("MODEL_JARVIS_ORCHESTRATOR","qwen/qwen3.5-122b-a10b"),
    "strategic_planning": os.getenv("MODEL_STRATEGIC_PLANNING","qwen/qwen3.5-397b-a17b"),
    "marketing":          os.getenv("MODEL_MARKETING",         "mistral/mistral-large-3"),
    "creative":           os.getenv("MODEL_CREATIVE",          "mistral/mistral-medium"),
}


# --------------------------------------------------
# COST ESTIMATES (per 1k tokens, USD)
# Used for tracking when DB pricing table is unavailable
# --------------------------------------------------

COST_MAP = {
    "moonshotai/kimi-k2.5":                       0.0,
    "qwen/qwen3.5-397b-a17b":                     0.0,
    "qwen/qwen3.5-122b-a10b":                     0.0,
    "meta/llama-4-maverick-17b-128e-instruct":    0.0,
    "meta/llama-4-scout-17b-16e-instruct":        0.0,
    "deepseek-ai/deepseek-v3.2":                  0.0,
    "mistral/mistral-large-3":                    0.0,
    "gpt-4o":                                     0.005,
    "gpt-4o-mini":                                0.00015,
}


def _estimate_cost(model: str, tokens: int) -> float:
    rate = COST_MAP.get(model, 0.0)
    return round(rate * tokens / 1000, 6)


# --------------------------------------------------
# PROVIDER ROUTING
# --------------------------------------------------

def _is_openai_model(model: str) -> bool:
    if model.startswith("openai/"):
        return True
    if model.startswith("gpt-"):
        return True
    return False


def _normalize_model(model: str) -> tuple:
    """Returns (provider, clean_model_id)"""
    if model.startswith("openai/"):
        return "openai", model[len("openai/"):]
    if model.startswith("gpt-"):
        return "openai", model
    if model.startswith("nvidia-nim/"):
        return "nvidia", model[len("nvidia-nim/"):]
    return "nvidia", model


# --------------------------------------------------
# CORE LLM CALL
# --------------------------------------------------

def _call_nvidia(model: str, messages: list, timeout: int) -> dict:
    if not NVIDIA_KEY:
        raise RuntimeError("NVIDIA_API_KEY not set")

    url = f"{NVIDIA_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {NVIDIA_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 2048,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    msg = data["choices"][0]["message"]
    content = msg.get("content") or msg.get("reasoning_content") or ""
    usage = data.get("usage", {})

    return {
        "content": content.strip(),
        "tokens": usage.get("total_tokens", 0),
        "tokens_input": usage.get("prompt_tokens", 0),
        "tokens_output": usage.get("completion_tokens", 0),
        "provider": "nvidia",
        "model": model,
    }


def _call_openai(model: str, messages: list, timeout: int) -> dict:
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 2048,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})

    return {
        "content": content,
        "tokens": usage.get("total_tokens", 0),
        "tokens_input": usage.get("prompt_tokens", 0),
        "tokens_output": usage.get("completion_tokens", 0),
        "provider": "openai",
        "model": model,
    }


# --------------------------------------------------
# NVIDIA FALLBACK CHAIN
# --------------------------------------------------

NVIDIA_FALLBACK_CHAIN = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "meta/llama-3.3-70b-instruct",
    "deepseek-ai/deepseek-v3.2",
]


def _call_with_fallback(model: str, messages: list, timeout: int) -> dict:
    provider, clean_model = _normalize_model(model)

    if provider == "openai" or FORCE_FREE is False and _is_openai_model(model):
        try:
            return _call_openai(clean_model, messages, timeout)
        except Exception as e:
            if FORCE_FREE:
                raise
            print(f"[MCP:llm_router] OpenAI failed ({e}), trying NVIDIA", flush=True)

    # NVIDIA path with fallback chain
    attempts = [clean_model] + [m for m in NVIDIA_FALLBACK_CHAIN if m != clean_model]
    last_error = None

    for attempt in attempts:
        try:
            result = _call_nvidia(attempt, messages, timeout)
            if result["content"]:
                if attempt != clean_model:
                    print(f"[MCP:llm_router] Used fallback model: {attempt}", flush=True)
                return result
        except Exception as e:
            last_error = e
            print(f"[MCP:llm_router] {attempt} failed: {str(e)[:80]}", flush=True)
            continue

    # Last resort: OpenAI
    if not FORCE_FREE and OPENAI_KEY:
        try:
            return _call_openai("gpt-4o-mini", messages, 60)
        except Exception as e:
            last_error = e

    raise RuntimeError(f"All LLM providers failed. Last: {last_error}")


# --------------------------------------------------
# USAGE TRACKING
# --------------------------------------------------

def _track_usage(model: str, provider: str, tokens_in: int, tokens_out: int, cost: float, agent: str = "", chain_id: str = ""):
    """Track usage in Redis AND post to API for persistent storage."""
    try:
        key = f"usage:{model}:today"
        _r.incrbyfloat(key, cost)
        _r.expire(key, 86400)

        key2 = f"usage:total:today"
        _r.incrbyfloat(key2, cost)
        _r.expire(key2, 86400)

        # Write to Postgres jobs table for metrics dashboard
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO jobs (id, type, status, payload, tokens_input, tokens_output, estimated_cost_usd, provider, model_used, completed_at)
                VALUES (gen_random_uuid(), 'mcp_llm_call', 'completed', %s, %s, %s, %s, %s, %s, NOW())
            """, (
                json.dumps({"agent": agent}),
                tokens_in, tokens_out, cost, provider, model
            ))
            conn.commit()
            cur.close()
            conn.close()
    except Exception as e:
        print(f"[MCP:llm_router] Usage tracking error: {e}", flush=True)

    # Post to API for persistent per-request tracking
    try:
        api_base = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
        requests.post(f"{api_base}/metrics/llm/record", json={
            "agent": agent, "model": model, "provider": provider,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "cost_usd": cost, "chain_id": chain_id,
        }, timeout=3)
    except Exception:
        pass  # Never fail on metrics


# --------------------------------------------------
# TOOL IMPLEMENTATIONS
# --------------------------------------------------

def tool_run(params: dict) -> dict:
    model       = params.get("model") or "qwen/qwen3.5-122b-a10b"
    messages    = params.get("messages", [])
    timeout     = int(params.get("timeout", 60))
    agent       = params.get("agent", "")

    if not messages:
        raise ValueError("messages required")

    t0 = time.time()
    result = _call_with_fallback(model, messages, timeout)
    elapsed = round(time.time() - t0, 2)

    cost = _estimate_cost(result["model"], result["tokens"])
    result["cost_usd"] = cost
    result["elapsed_sec"] = elapsed

    _track_usage(
        result["model"],
        result["provider"],
        result.get("tokens_input", 0),
        result.get("tokens_output", 0),
        cost,
        agent
    )

    return result


def tool_get_model_for_role(params: dict) -> str:
    role = params.get("role", "fast")
    return ROLE_MODEL_MAP.get(role, ROLE_MODEL_MAP["fast"])


def tool_get_usage_today(params: dict) -> dict:
    try:
        total = float(_r.get("usage:total:today") or 0)
        by_model = {}
        for model in COST_MAP:
            key = f"usage:{model}:today"
            val = _r.get(key)
            if val:
                by_model[model] = float(val)
        return {"cost_usd": round(total, 6), "by_model": by_model}
    except Exception as e:
        return {"error": str(e)}


def tool_list_models(params: dict) -> list:
    return [
        {"id": model, "provider": "nvidia" if "/" in model else "openai", "cost_per_1k": cost}
        for model, cost in COST_MAP.items()
    ]


# --------------------------------------------------
# SERVER ASSEMBLY
# --------------------------------------------------

class LLMRouterServer(MCPServer):
    def __init__(self):
        super().__init__("llm_router")
        self.register_tool("run",                tool_run)
        self.register_tool("get_model_for_role", tool_get_model_for_role)
        self.register_tool("get_usage_today",    tool_get_usage_today)
        self.register_tool("list_models",        tool_list_models)


if __name__ == "__main__":
    server = LLMRouterServer()
    server.run()
