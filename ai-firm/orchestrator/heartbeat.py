import time
import os
from shared.job_submitter import submit_job
from orchestrator.main import DOCTRINE_CONTENT
from task_router import dispatch_task
from shared.redis_bus import publish

HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "1800"))
print(f"[AUTONOMY] Heartbeat interval set to {HEARTBEAT_INTERVAL} seconds")

def run_heartbeat():
    print("Jarvis heartbeat started.")

    while True:
        try:
            # Strategic Build Stream
            dispatch_task("research", "market_scan", {"focus": "Silent Empire positioning"})
            dispatch_task("growth", "content_plan", {"window": "30_days"})
            dispatch_task("product", "crm_design", {"version": "v1"})
            dispatch_task("revenue", "offer_stack", {"target": "trust_system"})
            dispatch_task("legal", "risk_review", {"scope": "marketing_claims"})
            dispatch_task("systems", "optimize_workflows", {"priority": "high"})

            # Sales monitoring (not forced dispatch)
            publish("agent.sales.monitor", {"type": "status_check"})

            print("Jarvis dispatched strategic parallel tasks.")

            time.sleep(60)

        except Exception as e:
            print(f"Heartbeat error: {e}")
            time.sleep(10)

def hybrid_autonomy_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)

        if os.getenv("AUTONOMY_MODE", "true") != "true":
            continue

        founder_active = False  # placeholder for ClickUp detection

        if founder_active:
            continue

        print("[AUTONOMY] Founder idle — initiating doctrine-aligned initiative")

        submit_job(
            "empire_autonomous_initiative",
            {"mode": "hybrid"},
            doctrine=DOCTRINE_CONTENT
        )
