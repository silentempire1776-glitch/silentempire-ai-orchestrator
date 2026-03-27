"""
=========================================================
Sales Agent — Elite Sales Architecture Module
Durable + Idempotent Guard (Hardened)
=========================================================
"""

import json
import time
from typing import Any
from shared.redis_bus import enqueue, dequeue_blocking
from shared.job_submitter import submit_job
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed

AGENT_NAME = "sales"

QUEUE_NAME = "queue.agent.sales"
RETRY_QUEUE = "queue.agent.sales.retry"
DEAD_QUEUE = "queue.agent.sales.dead"

MAX_RETRIES = 3


# --------------------------------------------------
# SAFE DICT NORMALIZER
# --------------------------------------------------

def _as_dict(obj: Any):
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except Exception:
        return {}


# --------------------------------------------------
# SALES INSTRUCTION BUILDER
# --------------------------------------------------

def build_sales_instruction(executive, identity, soul, artifact):

    upstream_data = {}

    if artifact and isinstance(artifact, dict):
        upstream_data = artifact.get("data", {})

    return f"""
=== EXECUTIVE STACK ===
{executive}

=== AGENT IDENTITY ===
{identity}

=== AGENT SOUL ===
{soul}

=== UPSTREAM OFFER ARCHITECTURE ===
{json.dumps(upstream_data, indent=2)}

You are the Elite Sales Architect.

Transform the revenue offer architecture into:

1. Core Sales Narrative
2. Identity-Based Hook
3. Emotional Open Loop
4. Mechanism Explanation (clear, simple)
5. Objection Handling Framework
6. Authority Positioning
7. Call-To-Action Structure
8. Follow-Up Sequence Outline
9. Close Script (consultative, not manipulative)
10. Urgency Drivers (ethical)

Structured.
Persuasive.
Clear.
No hype.
"""


# --------------------------------------------------
# TASK PROCESSOR (HARDENED)
# --------------------------------------------------

def process_task(raw_envelope):

    envelope = _as_dict(raw_envelope)

    # 🔒 HARD GUARD — ENVELOPE VALIDATION
    if not isinstance(envelope, dict) or not envelope:
        print("[SALES] Skipping invalid envelope", flush=True)
        return

    doctrine = _as_dict(envelope.get("doctrine"))
    executive = doctrine.get("executive", "")
    identity = doctrine.get("identity", "")
    soul = doctrine.get("soul", "")

    task_type = envelope.get("task_type")

    payload = _as_dict(envelope.get("payload"))
    upstream_artifact = _as_dict(envelope.get("result")) or payload

    chain_id = payload.get("chain_id")

    # 🔒 HARD GUARD — TASK VALIDATION
    if not task_type or not isinstance(payload, dict):
        print(f"[SALES] Skipping invalid task | task_type={task_type}", flush=True)
        return

    # ---------------------------
    # IDEMPOTENT GUARD
    # ---------------------------
    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[SALES] Stage already completed for {chain_id}, skipping.", flush=True)
        return

    print(f"[SALES] Processing task: {task_type} | chain_id={chain_id}", flush=True)

    # --- CHAT PASSTHROUGH (non-regressive) ---
    if task_type == "chat":
        msg = payload.get("message")
        if msg is None:
            msg = payload.get("product")

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME,
            "task_type": "chat",
            "result": {
                "artifact_type": "chat_echo",
                "version": "1.0",
                "data": {
                    "text": f"[Sales Agent] Received: {msg}"
                }
            },
            "payload": payload,
            "doctrine": doctrine
        })
        return
    # --- END CHAT PASSTHROUGH ---

    if task_type != "offer_stack":
        print(f"[SALES] Unknown task type: {task_type}", flush=True)
        return

    instruction = build_sales_instruction(
        executive,
        identity,
        soul,
        upstream_artifact
    )

    # ---------------------------
    # AI EXECUTION
    # ---------------------------
    result = submit_job("ai_task", {
        "instruction": instruction,
        "agent": AGENT_NAME
    })

    # ---------------------------
    # SAFE OUTPUT WRAP
    # ---------------------------
    if not result:
        result = {"error": "empty_response"}

    structured_output = build_artifact(
        "sales_architecture",
        "1.0",
        {
            "raw_sales_strategy": result
        }
    )

    # ---------------------------
    # MARK COMPLETE AFTER SUCCESS
    # ---------------------------
    if chain_id:
        mark_stage_completed(chain_id, AGENT_NAME)

    enqueue("queue.orchestrator.results", {
        "agent": AGENT_NAME,
        "task_type": task_type,
        "result": structured_output,
        "payload": payload,
        "doctrine": doctrine
    })


# --------------------------------------------------
# MAIN LOOP (WITH RETRY + DEAD LETTER)
# --------------------------------------------------

def run():
    print("[SALES] Elite Sales Architect online. (Durable Mode - Hardened)", flush=True)

    while True:
        try:
            envelope = dequeue_blocking(QUEUE_NAME)
            envelope = _as_dict(envelope)

            retry_count = envelope.get("retry_count", 0)

            try:
                process_task(envelope)

            except Exception as error:
                retry_count += 1
                envelope["retry_count"] = retry_count

                print(f"[SALES ERROR] Task failure | retry={retry_count} | error={error}", flush=True)

                if retry_count < MAX_RETRIES:
                    enqueue(RETRY_QUEUE, envelope)
                    print("[SALES] Sent to retry queue.", flush=True)
                else:
                    enqueue(DEAD_QUEUE, envelope)

                    enqueue("queue.orchestrator.results", {
                        "agent": AGENT_NAME,
                        "task_type": envelope.get("task_type"),
                        "result": {
                            "artifact_type": "error",
                            "version": "1.0",
                            "data": {
                                "error": str(error),
                                "retry_count": retry_count
                            }
                        },
                        "payload": envelope.get("payload"),
                        "doctrine": envelope.get("doctrine"),
                        "status": "failed"
                    })

                    print("[SALES] Moved to DEAD queue + notified orchestrator.", flush=True)

        except Exception as queue_error:
            print(f"[SALES ERROR] Queue failure: {queue_error}", flush=True)
            time.sleep(2)


# --------------------------------------------------

if __name__ == "__main__":
    run()

