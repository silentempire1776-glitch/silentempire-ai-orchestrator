"""
=========================================================
Growth Agent — Elite Distribution & Scale Architect
Version: 4.1 (Elite Hardened Merge)
Durable + Idempotent Guard + Retry + Dead Letter + Guards
=========================================================
"""

import json
import time
from typing import Any

from shared.redis_bus import enqueue, dequeue_blocking
from shared.job_submitter import submit_job
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed

AGENT_NAME = "growth"

QUEUE_NAME = "queue.agent.growth"
RETRY_QUEUE = "queue.agent.growth.retry"
DEAD_QUEUE = "queue.agent.growth.dead"

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
# GROWTH INSTRUCTION BUILDER (UNCHANGED)
# --------------------------------------------------

def build_growth_instruction(executive, identity, soul, artifact):

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

=== UPSTREAM SALES ARCHITECTURE ===
{json.dumps(upstream_data, indent=2)}

You are the Growth Architect.

Transform the sales architecture into:

1. ICP Refinement
2. Channel Strategy
3. Traffic Source Prioritization
4. Funnel Strategy
5. Content Angle Strategy
6. Paid Acquisition Opportunities
7. Organic Leverage Strategy
8. Authority Positioning Strategy
9. Compounding Growth Loops
10. Scaling Roadmap

Strategic.
Structured.
Leverage-focused.
"""


# --------------------------------------------------
# TASK PROCESSOR (HARDENED — PRESERVES LOGIC)
# --------------------------------------------------

def process_task(raw_envelope):

    envelope = _as_dict(raw_envelope)

    # 🔒 ENVELOPE GUARD
    if not isinstance(envelope, dict) or not envelope:
        print("[GROWTH] Skipping invalid envelope", flush=True)
        return

    doctrine = _as_dict(envelope.get("doctrine"))

    executive = doctrine.get("executive", "")
    identity = doctrine.get("identity", "")
    soul = doctrine.get("soul", "")

    task_type = envelope.get("task_type")

    payload = _as_dict(envelope.get("payload"))
    upstream_artifact = envelope.get("result") or payload
    upstream_artifact = _as_dict(upstream_artifact)

    chain_id = payload.get("chain_id")

    # 🔒 TASK VALIDATION
    if not task_type or not isinstance(payload, dict):
        print(f"[GROWTH] Skipping invalid task | task_type={task_type}", flush=True)
        return

    # IDEMPOTENT GUARD (PRESERVED)
    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[GROWTH] Stage already completed for {chain_id}, skipping.", flush=True)
        return

    print(f"[GROWTH] Processing task: {task_type} | chain_id={chain_id}", flush=True)

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
                    "text": f"[Growth Agent] Received: {msg}"
                }
            },
            "payload": payload,
            "doctrine": doctrine
        })
        return
    # --- END CHAT PASSTHROUGH ---

    if task_type != "offer_stack":
        print(f"[GROWTH] Unknown task type: {task_type}", flush=True)
        return

    instruction = build_growth_instruction(
        executive,
        identity,
        soul,
        upstream_artifact
    )

    # AI EXECUTION (UNCHANGED CORE)
    result = submit_job("ai_task", {
        "instruction": instruction,
        "agent": AGENT_NAME
    })

    # 🔒 SAFE OUTPUT
    if not result:
        result = {"error": "empty_response"}

    structured_output = build_artifact(
        "growth_strategy",
        "1.0",
        {
            "raw_growth_strategy": result
        }
    )

    # MARK COMPLETE
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
# MAIN LOOP (RETRY + DEAD LETTER — PRESERVED + HARDENED)
# --------------------------------------------------

def run():
    print("[GROWTH] Elite Growth Architect online. (Durable + Retry Mode)", flush=True)

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

                print(f"[GROWTH ERROR] Task failure | retry={retry_count} | error={error}", flush=True)

                if retry_count < MAX_RETRIES:
                    enqueue(RETRY_QUEUE, envelope)
                    print("[GROWTH] Sent to retry queue.", flush=True)
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

                    print("[GROWTH] Moved to DEAD queue + notified orchestrator.", flush=True)

        except Exception as queue_error:
            print(f"[GROWTH ERROR] Queue failure: {queue_error}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    run()
