import os, requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

def chain_event(chain_id: str, payload: dict, timeout: int = 10):
    url = f"{API_BASE_URL}/chains/{chain_id}/event"
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def chain_started(chain_id: str):
    return chain_event(chain_id, {"event": "chain_started"})

def chain_completed(chain_id: str, results_by_agent: dict, ceo_summary: str):
    return chain_event(chain_id, {
        "event": "chain_completed",
        "meta": {
            "results_by_agent": results_by_agent,
            "ceo_summary": ceo_summary
        }
    })

def step_started(chain_id: str, agent: str):
    return chain_event(chain_id, {"event": "step_started", "agent": agent})

def step_completed(chain_id: str, agent: str, output: str, meta: dict | None = None):
    payload = {"event": "step_completed", "agent": agent, "output": output}
    if meta:
        payload["meta"] = meta
    return chain_event(chain_id, payload)

def step_failed(chain_id: str, agent: str, error: str):
    return chain_event(chain_id, {"event": "step_failed", "agent": agent, "error": error})
