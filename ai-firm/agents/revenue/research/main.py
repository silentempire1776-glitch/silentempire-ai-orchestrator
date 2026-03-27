"""
=========================================================
Research Agent — Elite Strategic Intelligence Module
Hardened Envelope Parsing + Chain Telemetry (Option B)
=========================================================
"""

import os
import json
import time
import traceback
from typing import Any, Dict, Tuple, Optional

import requests

from shared.redis_bus import enqueue, dequeue_blocking
from shared.job_submitter import submit_job
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed

AGENT_NAME = "research"
QUEUE_NAME = "queue.agent.research"

# Internal API (inside docker network)
API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

CHAIN_EVENT_TIMEOUT = 5
JOB_POLL_SLEEP = 1.5
JOB_POLL_MAX_SECONDS = 120


# --------------------------------------------------
# SAFE NORMALIZERS
# --------------------------------------------------

def _as_dict(x: Any) -> Dict[str, Any]:
    """
    Normalize envelope / job objects into dict.
    Handles: dict, bytes, JSON string, JSON-string-containing-JSON.
    """
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    if isinstance(x, (bytes, bytearray)):
        x = x.decode("utf-8", errors="replace")
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return {}
        # First parse
        try:
            parsed = json.loads(s)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        # Sometimes redis payload is JSON string of JSON
        if isinstance(parsed, str):
            parsed2 = json.loads(parsed)
            if isinstance(parsed2, dict):
                return parsed2
        # Not a dict -> wrap
        return {"_value": parsed}
    # Unknown type -> wrap
    return {"_value": str(x)}


def _normalize_doctrine(doctrine_any: Any) -> Dict[str, str]:
    """
    Doctrine may be:
      - dict {"executive":..,"identity":..,"soul":..}
      - raw string (whole doc)
    """
    if doctrine_any is None:
        return {"executive": "", "identity": "", "soul": ""}

    if isinstance(doctrine_any, dict):
        return {
            "executive": doctrine_any.get("executive", "") or "",
            "identity": doctrine_any.get("identity", "") or "",
            "soul": doctrine_any.get("soul", "") or "",
        }

    # raw doctrine text
    if isinstance(doctrine_any, (bytes, bytearray)):
        doctrine_any = doctrine_any.decode("utf-8", errors="replace")

    if isinstance(doctrine_any, str):
        text = doctrine_any.strip()
        return {"executive": text, "identity": "", "soul": ""}

    return {"executive": str(doctrine_any), "identity": "", "soul": ""}


# --------------------------------------------------
# CHAIN TELEMETRY (Option B)
# --------------------------------------------------

def _post_chain_event(chain_id: Optional[str],
                     event: str,
                     agent: Optional[str] = None,
                     output: Optional[str] = None,
                     meta: Optional[Dict[str, Any]] = None,
                     error: Optional[str] = None) -> None:
    if not chain_id:
        return
    try:
        url = f"{API_BASE_URL}/chains/{chain_id}/event"
        payload: Dict[str, Any] = {"event": event}
        if agent:
            payload["agent"] = agent
        if output is not None:
            payload["output"] = output
        if meta is not None:
            payload["meta"] = meta
        if error is not None:
            payload["error"] = error

        requests.post(url, json=payload, timeout=CHAIN_EVENT_TIMEOUT)
    except Exception:
        # Never allow telemetry to crash agent
        pass


# --------------------------------------------------
# INSTRUCTION BUILDER
# --------------------------------------------------

def build_research_instruction(executive: str, identity: str, soul: str, payload: Dict[str, Any]) -> str:
    payload = _as_dict(payload)
    target = payload.get("target", "")
    product = payload.get("product", "")

    return f"""
=== EXECUTIVE STACK ===
{executive}

=== AGENT IDENTITY ===
{identity}

=== AGENT SOUL ===
{soul}

You are the Strategic Research Architect.

Target Market: {target}
Product/System: {product}

Perform elite-level research:

1. Market Landscape Analysis
2. Competitive Positioning
3. Demand Signals
4. Pain Point Clusters
5. Desire Mapping
6. Market Sophistication Level
7. White Space Opportunities
8. Economic Leverage Opportunities
9. Offer Angle Hypotheses
10. Strategic Risk Factors

CRITICAL:
You MUST return STRICT VALID JSON.
No commentary. No markdown. No text outside JSON.

Return EXACTLY this structure:

{{
  "artifact_type": "strategic_research",
  "version": 1,
  "market_landscape": "",
  "competitive_positioning": "",
  "demand_signals": "",
  "pain_point_clusters": [],
  "desire_mapping": [],
  "market_sophistication_level": "",
  "white_space_opportunities": [],
  "economic_leverage_opportunities": [],
  "offer_angle_hypotheses": [],
  "strategic_risk_factors": []
}}
""".strip()

# --------------------------------------------------
# JOB EXECUTION
# --------------------------------------------------

def _create_job(instruction: str) -> str:
    url = f"{API_BASE_URL}/jobs"
    payload = {
        "type": "ai_task",
        "payload": {
            "instruction": instruction,
            "agent": AGENT_NAME
        }
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    data = _as_dict(r.json())
    job_id = data.get("job_id") or data.get("id")
    if not job_id:
        raise RuntimeError(f"No job_id returned from /jobs. resp={data}")
    return str(job_id)


def _wait_job(job_id: str) -> Dict[str, Any]:
    url = f"{API_BASE_URL}/jobs/{job_id}"
    start = time.time()
    while True:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = _as_dict(r.json())
        status = (data.get("status") or "").lower()

        if status in ("completed", "failed", "archived"):
            return data

        if time.time() - start > JOB_POLL_MAX_SECONDS:
            raise TimeoutError(f"Job {job_id} did not finish within {JOB_POLL_MAX_SECONDS}s")

        time.sleep(JOB_POLL_SLEEP)


def _parse_model_output(job_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    meta = {
        "job_id": job_data.get("id"),
        "provider": job_data.get("provider"),
        "model_used": job_data.get("model_used"),
    }

    result_text = job_data.get("result")
    if result_text is None:
        return ({"artifact_type": "strategic_research", "version": 1, "raw_output": ""}, meta)

    if isinstance(result_text, (dict, list)):
        return ({"artifact_type": "strategic_research", "version": 1, "data": result_text}, meta)

    if isinstance(result_text, str):
        rt = result_text.strip()
        try:
            parsed = json.loads(rt)
            if isinstance(parsed, dict):
                return (parsed, meta)
            return ({"artifact_type": "strategic_research", "version": 1, "data": parsed}, meta)
        except Exception:
            return ({"artifact_type": "strategic_research", "version": 1, "raw_output": rt}, meta)

    return ({"artifact_type": "strategic_research", "version": 1, "raw_output": str(result_text)}, meta)


# --------------------------------------------------
# PROCESS TASK
# --------------------------------------------------

def process_task(raw_envelope: Any) -> None:
    envelope = _as_dict(raw_envelope)

    doctrine_raw = _as_dict(envelope.get("doctrine"))
    doctrine = _as_dict(doctrine_raw)

    executive = doctrine.get("executive", "")
    identity = doctrine.get("identity", "")
    soul = doctrine.get("soul", "")

    task_type = envelope.get("task_type")

    payload = _as_dict(envelope.get("payload"))
    chain_id = payload.get("chain_id")

    # Idempotent guard
    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[RESEARCH] Stage already completed for {chain_id}, skipping.", flush=True)
        return

    print(f"[RESEARCH] Processing task: {task_type} chain_id={chain_id}", flush=True)

    if task_type != "offer_stack":
        print(f"[RESEARCH] Unknown task type: {task_type}", flush=True)
        return

    _post_chain_event(chain_id, "step_started", agent=AGENT_NAME)

    instruction = build_research_instruction(executive, identity, soul, payload)

    # Create + wait job (do not rely on ambiguous submit_job return types)
    job_id = _create_job(instruction)
    job_data = _wait_job(job_id)

    if (job_data.get("status") or "").lower() != "completed":
        err = job_data.get("error_message") or "ai_task failed"
        _post_chain_event(chain_id, "step_failed", agent=AGENT_NAME, error=str(err))
        raise RuntimeError(f"ai_task failed: {err}")

    parsed, meta = _parse_model_output(job_data)

    structured_output = build_artifact(
        parsed.get("artifact_type", "strategic_research"),
        str(parsed.get("version", 1)),
        parsed
    )

    # Mark stage completed only after success
    if chain_id:
        mark_stage_completed(chain_id, AGENT_NAME)

    _post_chain_event(
        chain_id,
        "step_completed",
        agent=AGENT_NAME,
        output=json.dumps(parsed),
        meta=meta
    )

    enqueue("queue.orchestrator.results", {
        "agent": AGENT_NAME,
        "task_type": task_type,
        "status": "ok",
        "result": structured_output,
        "payload": payload,
        "doctrine": doctrine
    })


# --------------------------------------------------
# MAIN LOOP
# --------------------------------------------------

def run() -> None:
    print("[RESEARCH] Elite Strategic Research Module online. (Durable Mode)", flush=True)

    while True:
        try:
            raw = dequeue_blocking(QUEUE_NAME)
            process_task(raw)

        except Exception as error:
            tb = traceback.format_exc()
            print(f"[RESEARCH ERROR] {error}", flush=True)
            print(tb, flush=True)
            # Always try to write a trace for offline inspection
            try:
                with open("/tmp/research_trace.log", "a") as f:
                    f.write("\n=== ERROR ===\n")
                    f.write(str(error) + "\n")
                    f.write(tb + "\n")
                    f.flush()
            except Exception:
                pass
            time.sleep(2)


if __name__ == "__main__":
    run()
