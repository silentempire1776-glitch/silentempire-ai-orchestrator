"""
Shared metrics tracker for all Silent Empire agents.
Call track_llm_call() after any direct NVIDIA/LLM response.
"""
import os
import requests as _req

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

def track_llm_call(agent: str, model: str, usage: dict, provider: str = "nvidia", chain_id: str = "") -> None:
    """
    Post token usage to /metrics/llm/record after an LLM call.
    usage = data.get("usage", {}) from the NVIDIA/OpenAI response.
    Never raises — metrics must never break agent execution.
    """
    try:
        ti  = int(usage.get("prompt_tokens", 0) or 0)
        to_ = int(usage.get("completion_tokens", 0) or 0)
        if not ti and not to_:
            return
        _req.post(f"{API_BASE_URL}/metrics/llm/record", json={
            "agent":        agent,
            "model":        model,
            "provider":     provider,
            "tokens_in":    ti,
            "tokens_out":   to_,
            "tokens_total": ti + to_,
            "cost_usd":     0.0,
            "chain_id":     chain_id,
        }, timeout=2)
    except Exception:
        pass

def track_agent_working(agent: str, chain_id: str) -> None:
    """Post step_started to chain_events so dashboard shows agent as working."""
    try:
        if not chain_id:
            return
        _req.post(f"{API_BASE_URL}/chains/{chain_id}/event", json={
            "event": "step_started",
            "agent": agent,
        }, timeout=2)
    except Exception:
        pass

def track_agent_done(agent: str, chain_id: str, output: str = "") -> None:
    """Post step_completed to chain_events so dashboard shows agent as idle."""
    try:
        if not chain_id:
            return
        _req.post(f"{API_BASE_URL}/chains/{chain_id}/event", json={
            "event":  "step_completed",
            "agent":  agent,
            "output": output[:500] if output else "",
        }, timeout=2)
    except Exception:
        pass
