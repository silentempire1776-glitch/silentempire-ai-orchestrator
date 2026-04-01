"""
Sales Agent — Version 6.0
Fixed: job waiting + file writing + markdown output
"""

import json
import os
import time
import traceback
from typing import Any, Dict

from shared.redis_bus import enqueue, dequeue_blocking
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed
from job_runner import (submit_and_wait, submit_and_wait_with_eval,
                        extract_save_path, write_report,
                        read_agent_memory, write_agent_memory, summarize_to_memory)
from config_loader import get_agent_config, get_company_name

AGENT_NAME  = "sales"
QUEUE_NAME  = "queue.agent.sales"
RETRY_QUEUE = "queue.agent.sales.retry"
DEAD_QUEUE  = "queue.agent.sales.dead"
MAX_RETRIES = 3


def _as_dict(obj: Any) -> Dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8", errors="replace")
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    try:
        return dict(obj)
    except Exception:
        return {}


def build_instruction(executive, identity, soul, payload):
    _agent_cfg  = get_agent_config(AGENT_NAME)
    role_title  = _agent_cfg.get("role_title", "Agent")
    company_name = get_company_name()
    instruction = (
        payload.get("instruction") or
        payload.get("message") or
        payload.get("target") or
        payload.get("product") or
        "Perform your specialist analysis."
    )
    save_path = extract_save_path(instruction)
    file_note = f"\nYour output will be saved to: {save_path}" if save_path else ""

    return f"""=== EXECUTIVE STACK ===
{executive}

=== AGENT IDENTITY ===
{identity}

=== AGENT SOUL ===
{soul}

You are the {role_title} for {company_name}.
Deliver a professional sales strategy report in markdown format.
Cover: Sales Narrative, Identity-Based Hook, Emotional Open Loop,
Mechanism Explanation, Objection Handling, Authority Positioning,
Call-To-Action Structure, Follow-Up Sequence, Close Script, Urgency Drivers.
Be specific. Use proven sales psychology and real frameworks.

TASK:
{instruction}
{file_note}

Do NOT return JSON. Return a well-structured markdown document.
Do NOT add preamble — start directly with the content.
Do NOT add any note or disclaimer about filesystem access, file saving, or language model limitations — file saving is handled automatically by the system after you return your content.
""".strip()


def process_task(raw_envelope):
    envelope = _as_dict(raw_envelope)
    if not isinstance(envelope, dict) or not envelope:
        print("[SALES] Skipping invalid envelope", flush=True)
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
        print("[SALES] Missing task_type, skipping", flush=True)
        return

    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[SALES] Stage already completed: {chain_id}", flush=True)
        return

    print(f"[SALES] Processing task_type={task_type} chain_id={chain_id}", flush=True)

    if task_type == "chat":
        message = payload.get("message") or payload.get("product", "")
        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)
        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": "chat", "status": "ok",
            "result": build_artifact("chat_echo", "1.0", {"text": f"[Sales Agent] Received: {message}"}),
            "payload": payload, "doctrine": envelope.get("doctrine"),
        })
        return

    instruction = build_instruction(executive, identity, soul, payload)
    # Read agent memory and inject into instruction
    _memory = read_agent_memory(AGENT_NAME)
    if _memory:
        instruction = instruction + f"\n\n=== SALES AGENT MEMORY ===\n{_memory[:800]}\n=== END MEMORY ==="
    
    _task_desc = payload.get('instruction') or payload.get('message') or ''
    result_text = submit_and_wait_with_eval(AGENT_NAME, instruction, _task_desc)

    save_path = extract_save_path(payload.get("instruction") or payload.get("message") or "")
    file_written = None
    if save_path and result_text:
        if write_report(save_path, result_text, AGENT_NAME):
            file_written = save_path

    if chain_id:
        mark_stage_completed(chain_id, AGENT_NAME)

    enqueue("queue.orchestrator.results", {
        "agent": AGENT_NAME, "task_type": task_type, "status": "ok",
        "result": build_artifact("sales_report", "2.0", {
            "report": result_text, "file_written": file_written, "agent": AGENT_NAME,
        }),
        "payload": payload, "doctrine": envelope.get("doctrine"),
    })
    print(f"[SALES] Complete. file_written={file_written}", flush=True)


def run():
    print("[SALES] Sales Agent online. v6.0", flush=True)
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
                print(f"[SALES ERROR] retry={retry_count} | {error}", flush=True)
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
            print(f"[SALES QUEUE ERROR] {queue_error}", flush=True)
            time.sleep(2)

if __name__ == "__main__":
    run()
