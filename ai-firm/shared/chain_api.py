import os
import requests
from typing import Optional, Dict, Any

API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")

def post_chain_event(
    chain_id: str,
    event: str,
    agent: Optional[str] = None,
    output: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    timeout: int = 10,
):
    if not API_BASE_URL:
        # Don’t crash orchestrator if env not set; just no-op
        return

    url = f"{API_BASE_URL}/chains/{chain_id}/event"
    payload: Dict[str, Any] = {"event": event}

    if agent is not None:
        payload["agent"] = agent
    if output is not None:
        payload["output"] = output
    if meta is not None:
        payload["meta"] = meta
    if error is not None:
        payload["error"] = error

    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
    except Exception:
        # Never let telemetry kill the chain
        pass
