"""
Research Agent — Elite Strategic Intelligence Module
Version: 6.0 — Fixed job waiting + file writing + markdown output
"""

import json
import os
import time
import traceback
from typing import Any, Dict, Optional

import requests

from shared.redis_bus import enqueue, dequeue_blocking
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed
from job_runner import (submit_and_wait, submit_and_wait_with_eval,
                        extract_save_path, write_report,
                        read_agent_memory, write_agent_memory, summarize_to_memory)
from config_loader import get_agent_config, get_company_name

AGENT_NAME  = "research"
QUEUE_NAME  = "queue.agent.research"
RETRY_QUEUE = "queue.agent.research.retry"
DEAD_QUEUE  = "queue.agent.research.dead"
MAX_RETRIES = 3
API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
CHAIN_EVENT_TIMEOUT = 5


def _as_dict(x: Any) -> Dict[str, Any]:
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
        try:
            parsed = json.loads(s)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str):
            try:
                p2 = json.loads(parsed)
                if isinstance(p2, dict):
                    return p2
            except Exception:
                pass
        return {"_value": parsed}
    return {"_value": str(x)}


def _post_chain_event(chain_id, event, agent=None, output=None, error=None):
    if not chain_id:
        return
    try:
        payload = {"event": event}
        if agent:  payload["agent"]  = agent
        if output: payload["output"] = output
        if error:  payload["error"]  = error
        requests.post(f"{API_BASE_URL}/chains/{chain_id}/event",
                      json=payload, timeout=CHAIN_EVENT_TIMEOUT)
    except Exception:
        pass


def build_research_instruction(executive, identity, soul, payload):
    _agent_cfg  = get_agent_config(AGENT_NAME)
    role_title  = _agent_cfg.get("role_title", "Agent")
    company_name = get_company_name()
    instruction = (
        payload.get("instruction") or
        payload.get("message") or
        payload.get("target") or
        payload.get("product") or
        "Perform strategic market research on the assigned topic."
    )

    save_path = extract_save_path(instruction)
    file_note = f"\nSave your completed report to: {save_path}" if save_path else ""

    # Pull any Perplexity context that was pre-fetched
    web_context = payload.get("web_context", "")
    web_section = f"\n=== CURRENT WEB RESEARCH DATA ===\n{web_context}\n===" if web_context else ""

    return f"""=== EXECUTIVE STACK ===
{executive}

You are the {role_title} for {company_name}.

TASK:
{instruction}
{file_note}
{web_section}

CRITICAL — EXECUTE IMMEDIATELY:
1. DO NOT ask for more information. You have everything you need.
2. DO NOT return a template or framework. Return actual research content.
3. Write as a senior analyst with deep domain knowledge.
4. Use real market dynamics, demographics, competitive context.
5. Minimum 600 words. Target 1000-2000 for standard tasks.
6. Start directly with content — no preamble.

OUTPUT FORMAT: Clean markdown with headers.
Structure: Executive Summary → Market Overview → Target Audience →
Key Opportunities → Key Risks → Strategic Recommendations → Next Steps
Do NOT add any note or disclaimer about filesystem access, file saving, or language model limitations — file saving is handled automatically by the system after you return your content.
""".strip()

def process_task(raw_envelope):
    envelope = _as_dict(raw_envelope)
    if not isinstance(envelope, dict) or not envelope:
        print("[RESEARCH] Skipping invalid envelope", flush=True)
        return

    doctrine_raw = envelope.get("doctrine", {})
    if isinstance(doctrine_raw, str):
        executive = doctrine_raw
        identity = soul = ""
    else:
        d = _as_dict(doctrine_raw)
        executive = d.get("executive", "")
        identity  = d.get("identity", "")
        soul      = d.get("soul", "")

    task_type = envelope.get("task_type")
    payload   = _as_dict(envelope.get("payload"))
    chain_id  = payload.get("chain_id") or envelope.get("chain_id")

    if not task_type:
        print("[RESEARCH] Missing task_type, skipping", flush=True)
        return

    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[RESEARCH] Stage already completed: {chain_id}", flush=True)
        return

    print(f"[RESEARCH] Processing task_type={task_type} chain_id={chain_id}", flush=True)

    if task_type == "chat":
        message = payload.get("message") or payload.get("product", "")
        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": "chat", "status": "ok",
            "result": {"message": f"[Research Agent] Received: {message}"},
            "payload": payload, "doctrine": envelope.get("doctrine"),
        })
        _post_chain_event(chain_id, "step_completed", agent=AGENT_NAME,
                          output=f"[Research Agent] Received: {message}")
        return

    _post_chain_event(chain_id, "step_started", agent=AGENT_NAME)
    instruction = build_research_instruction(executive, identity, soul, payload)
    # Read agent memory and inject into instruction
    _memory = read_agent_memory(AGENT_NAME)
    if _memory:
        instruction = instruction + f"\n\n=== RESEARCH AGENT MEMORY ===\n{_memory[:800]}\n=== END MEMORY ==="
    
    _task_desc = payload.get('instruction') or payload.get('message') or ''
    result_text = submit_and_wait_with_eval(AGENT_NAME, instruction, _task_desc)

    save_path = extract_save_path(payload.get("instruction") or payload.get("message") or "")
    file_written = None
    if save_path and result_text:
        if write_report(save_path, result_text, AGENT_NAME):
            file_written = save_path

    if chain_id:
        mark_stage_completed(chain_id, AGENT_NAME)

    _post_chain_event(chain_id, "step_completed", agent=AGENT_NAME,
                      output=result_text[:500] if result_text else "")

    enqueue("queue.orchestrator.results", {
        "agent": AGENT_NAME, "task_type": task_type, "status": "ok",
        "result": build_artifact("research_report", "2.0", {
            "report": result_text, "file_written": file_written, "agent": AGENT_NAME,
        }),
        "payload": payload, "doctrine": envelope.get("doctrine"),
    })
    print(f"[RESEARCH] Complete. file_written={file_written}", flush=True)


def run():
    print("[RESEARCH] Elite Strategic Research Module online. v6.0", flush=True)
    while True:
        try:
            raw = dequeue_blocking(QUEUE_NAME)
            envelope = _as_dict(raw)
            retry_count = envelope.get("retry_count", 0)
            try:
                process_task(envelope)
            except Exception as error:
                retry_count += 1
                envelope["retry_count"] = retry_count
                print(f"[RESEARCH ERROR] retry={retry_count} | {error}", flush=True)
                print(traceback.format_exc(), flush=True)
                if retry_count < MAX_RETRIES:
                    enqueue(RETRY_QUEUE, envelope)
                else:
                    enqueue(DEAD_QUEUE, envelope)
                    enqueue("queue.orchestrator.results", {
                        "agent": AGENT_NAME, "task_type": envelope.get("task_type"),
                        "result": build_artifact("error", "1.0", {"error": str(error), "retry_count": retry_count}),
                        "payload": envelope.get("payload"), "doctrine": envelope.get("doctrine"), "status": "failed",
                    })
        except Exception as queue_error:
            print(f"[RESEARCH QUEUE ERROR] {queue_error}", flush=True)
            time.sleep(2)

if __name__ == "__main__":
    run()
