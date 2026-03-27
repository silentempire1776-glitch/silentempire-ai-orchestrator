import os
import sys
import uuid
from shared.redis_bus import enqueue

# -----------------------------------------
# Ensure /ai-firm is on Python path
# -----------------------------------------

AI_FIRM_PATH = "/ai-firm"

if AI_FIRM_PATH not in sys.path:
    sys.path.append(AI_FIRM_PATH)

from shared.artifact_store import (
    create_chain_record,
    init_chain_table
)

# -----------------------------------------
# Ensure SQLite chain table exists
# -----------------------------------------

init_chain_table()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def launch_chain(target, product):
    chain_id = str(uuid.uuid4())

    # -----------------------------------------
    # CREATE CHAIN RECORD (CRITICAL)
    # -----------------------------------------

#    create_chain_record(
#        chain_id=chain_id,
#        target=target,
#        product=product,
#        status="started"
#    )

    create_chain_record(chain_id)

    # -----------------------------------------
    # BUILD PAYLOAD
    # -----------------------------------------

    payload = {
        "target": target,
        "product": product
    }

    # -----------------------------------------
    # SEND TO ORCHESTRATOR (CRITICAL FIX)
    # -----------------------------------------

    enqueue("queue.orchestrator", {
        "chain_id": chain_id,
        "task_type": "offer_stack",
        "payload": payload
    })

    return chain_id
