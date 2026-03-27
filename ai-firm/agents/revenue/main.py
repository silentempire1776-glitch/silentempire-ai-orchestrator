"""
=========================================================
Revenue Agent — Elite Offer Architecture Module
Durable + Idempotent Guard + Retry + Hardening (Elite Merge)
=========================================================
"""

import json
import time
from typing import Any

from shared.redis_bus import dequeue_blocking, enqueue
from shared.job_submitter import submit_job
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed

AGENT_NAME = "revenue"
QUEUE_NAME = "queue.agent.revenue"
RETRY_QUEUE = "queue.agent.revenue.retry"
DEAD_QUEUE = "queue.agent.revenue.dead"

MAX_RETRIES = 3


# --------------------------------------------------
# SAFE NORMALIZER (ADDED — NON-DESTRUCTIVE)
# --------------------------------------------------

def _as_dict(obj: Any):
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except Exception:
        return {}


# --------------------------------------------------
# BUILD OFFER INSTRUCTION (UNCHANGED)
# --------------------------------------------------

def build_offer_instruction(executive, identity, soul, payload, upstream_artifact):

    upstream_data = {}

    if upstream_artifact and isinstance(upstream_artifact, dict):
        upstream_data = upstream_artifact.get("data", {})

    target = payload.get("target", "")
    product = payload.get("product", "")

    return f"""
=== EXECUTIVE STACK ===
{executive}

=== AGENT IDENTITY ===
{identity}

=== AGENT SOUL ===
{soul}

You are the Elite Revenue Architect.

Target: {target}
Product: {product}

Use upstream strategic research below:

{json.dumps(upstream_data, indent=2)}

Now construct:

1. Core Offer
2. Value Stack
3. Pricing Strategy
4. Risk Reversal
5. Scarcity Lever
6. Monetization Path
7. LTV Expansion Strategy

Precise. Structured. Monetizable.
"""


# --------------------------------------------------
# PROCESS TASK (HARDENED — PRESERVES LOGIC)
# --------------------------------------------------

def process_task(raw_envelope):

    envelope = _as_dict(raw_envelope)

    # 🔒 ENVELOPE GUARD
    if not isinstance(envelope, dict) or not envelope:
        print("[REVENUE] Skipping invalid envelope", flush=True)
        return

    doctrine = _as_dict(envelope.get("doctrine"))

    executive = doctrine.get("executive", "")
    identity = doctrine.get("identity", "")
    soul = doctrine.get("soul", "")

    task_type = envelope.get("task_type")

    payload = _as_dict(envelope.get("payload"))
    upstream_artifact = _as_dict(envelope.get("result"))

    chain_id = payload.get("chain_id")

    # 🔒 TASK VALIDATION
    if not task_type or not isinstance(payload, dict):
        print(f"[REVENUE] Skipping invalid task | task_type={task_type}", flush=True)
        return

    # ---------------------------
    # IDEMPOTENT GUARD (PRESERVED)
    # ---------------------------
    if chain_id:
        result = stage_already_completed(chain_id, AGENT_NAME)
        print("DEBUG stage_already_completed:", result, flush=True)

        if result:
            print(f"[REVENUE] Stage already completed for {chain_id}, skipping.", flush=True)
            return

    print(f"[REVENUE] Processing task: {task_type} | chain_id={chain_id}", flush=True)

    # --- CHAT PASSTHROUGH (non-regressive) ---
    if task_type == "chat":
        msg = payload.get("message")
        if msg is None:
            msg = payload.get("product")

        # mark completed for idempotency
        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME,
            "task_type": "chat",
            "result": {
                "artifact_type": "chat_echo",
                "version": "1.0",
                "data": {
                    "text": f"[Revenue Agent] Received: {msg}"
                }
            },
            "payload": payload,
            "doctrine": doctrine
        })
        return
    # --- END CHAT PASSTHROUGH ---

    if task_type != "offer_stack":
        print(f"[REVENUE] Unknown task type: {task_type}", flush=True)
        return

    instruction = build_offer_instruction(
        executive,
        identity,
        soul,
        payload,
        upstream_artifact
    )

    # ---------------------------
    # AI EXECUTION (UNCHANGED CORE)
    # ---------------------------
    result = submit_job("ai_task", {
        "instruction": instruction,
        "agent": AGENT_NAME
    })

    # 🔒 SAFE OUTPUT
    if not result:
        result = {"error": "empty_response"}

    structured_output = build_artifact(
        "revenue_architecture",
        "1.0",
        {
            "raw_revenue": result
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
# MAIN LOOP (RETRY + DEAD LETTER ADDED)
# --------------------------------------------------

def run():
    print("[REVENUE] Elite Revenue Architect online. (Durable + Retry Mode)", flush=True)

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

                print(f"[REVENUE ERROR] Task failure | retry={retry_count} | error={error}", flush=True)

                if retry_count < MAX_RETRIES:
                    enqueue(RETRY_QUEUE, envelope)
                    print("[REVENUE] Sent to retry queue.", flush=True)
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

                    print("[REVENUE] Moved to DEAD queue + notified orchestrator.", flush=True)

        except Exception as queue_error:
            print(f"[REVENUE ERROR] Queue failure: {queue_error}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    run()
