import time
import sqlite3
from datetime import datetime, timedelta
from shared.artifact_store import DB_PATH
from shared.redis_bus import enqueue

# ===============================================
# CONFIG
# ===============================================

BASE_TIMEOUT_SECONDS = 300        # 5 minutes base
MAX_RETRIES = 3                   # max attempts
BACKOFF_MULTIPLIER = 2            # exponential factor

# ===============================================
# TIMEOUT CHECK
# ===============================================

def calculate_backoff(retry_count):
    """
    Exponential backoff:
    0 retries -> 5 min
    1 retry   -> 10 min
    2 retries -> 20 min
    """
    return BASE_TIMEOUT_SECONDS * (BACKOFF_MULTIPLIER ** retry_count)


def check_timeouts():

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT chain_id, current_stage, stage_started_at, retry_count
        FROM chains
        WHERE status = 'running'
    """)

    rows = cursor.fetchall()
    now = datetime.utcnow()

    for chain_id, stage, started_at, retry_count in rows:

        if not started_at:
            continue

        started_time = datetime.fromisoformat(started_at)

        timeout_window = calculate_backoff(retry_count)

        if now - started_time > timedelta(seconds=timeout_window):

            print(f"[TIMEOUT] Chain {chain_id} stuck at {stage} (retry {retry_count})")

            if retry_count >= MAX_RETRIES:
                print(f"[FAILURE] Chain {chain_id} exceeded max retries")

                cursor.execute("""
                    UPDATE chains
                    SET status = 'failed',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE chain_id = ?
                """, (chain_id,))
            else:
                print(f"[RETRY] Re-enqueueing {chain_id} to {stage}")

                # increment retry_count and reset timer
                cursor.execute("""
                    UPDATE chains
                    SET retry_count = retry_count + 1,
                        stage_started_at = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE chain_id = ?
                """, (now.isoformat(), chain_id))

                # re-dispatch to correct agent queue
                enqueue(f"queue.agent.{stage}", {
                    "chain_id": chain_id,
                    "retry": True
                })

    conn.commit()
    conn.close()


# ===============================================
# MAIN LOOP
# ===============================================

def run():
    print("[Timeout Monitor] Enterprise backoff monitoring active")

    while True:
        check_timeouts()
        time.sleep(30)


if __name__ == "__main__":
    run()
