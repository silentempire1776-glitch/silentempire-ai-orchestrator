import os
import json
import sqlite3
import psycopg2
from datetime import datetime

# ==================================================
# CONFIG
# ==================================================

DATABASE_URL = os.getenv("DATABASE_URL")

ARTIFACT_DIR = "/srv/silentempire/ai-firm/logs/artifacts"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

DB_PATH = os.getenv(
    "ARTIFACT_DB_PATH",
    "/ai-firm/logs/artifacts.db"
)

# ==================================================
# POSTGRES ARTIFACT TABLE INIT
# ==================================================

def init_table():
    """
    Initializes artifact storage in Postgres
    and chain tracking table in SQLite.
    """

    # -------- Postgres Artifact Table --------
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id SERIAL PRIMARY KEY,
            chain_id TEXT,
            agent TEXT,
            artifact_type TEXT,
            version TEXT,
            created_at TIMESTAMP,
            data JSONB
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

    # -------- SQLite Chain Tracking --------
    init_chain_table()


# ==================================================
# SQLITE CHAIN TRACKING TABLE (UPDATED)
# ==================================================

def init_chain_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chains (
            chain_id TEXT PRIMARY KEY,
            status TEXT,
            current_stage TEXT,
            stage_started_at TEXT,
            retry_count INTEGER DEFAULT 0,
            completed_stages TEXT DEFAULT '[]',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def create_chain_record(chain_id, target=None, product=None, payload=None):
    if payload is None:
        payload = {}

    if target is not None and "target" not in payload:
        payload["target"] = target

    if product is not None and "product" not in payload:
        payload["product"] = product

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO chains
        (chain_id, status, current_stage, stage_started_at)
        VALUES (?, ?, ?, ?)
    """, (
        chain_id,
        "running",
        "research",
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()

def update_chain_status(chain_id, status=None, stage=None, stage_started_at=None, retry_count=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if status is not None:
        cursor.execute("""
            UPDATE chains
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE chain_id = ?
        """, (status, chain_id))

    if stage is not None:
        cursor.execute("""
            UPDATE chains
            SET current_stage = ?, updated_at = CURRENT_TIMESTAMP
            WHERE chain_id = ?
        """, (stage, chain_id))

    if stage_started_at is not None:
        cursor.execute("""
            UPDATE chains
            SET stage_started_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE chain_id = ?
        """, (stage_started_at, chain_id))

    if retry_count is not None:
        cursor.execute("""
            UPDATE chains
            SET retry_count = ?, updated_at = CURRENT_TIMESTAMP
            WHERE chain_id = ?
        """, (retry_count, chain_id))

    conn.commit()
    conn.close()

def get_running_chains():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM chains
        WHERE status = 'running'
    """)

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


# ==================================================
# SAVE ARTIFACT (POSTGRES + JSON MIRROR)
# ==================================================

def save_artifact(chain_id, agent, artifact_type, version, data):

    now = datetime.utcnow()

    # -------- Postgres Write --------
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO artifacts
        (chain_id, agent, artifact_type, version, created_at, data)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        chain_id,
        agent,
        artifact_type,
        version,
        now,
        json.dumps(data)
    ))

    conn.commit()
    cur.close()
    conn.close()

    # -------- JSON File Mirror --------
    filename = f"{chain_id}_{agent}_{int(now.timestamp())}.json"
    filepath = os.path.join(ARTIFACT_DIR, filename)

    with open(filepath, "w") as f:
        json.dump({
            "chain_id": chain_id,
            "agent": agent,
            "artifact_type": artifact_type,
            "version": version,
            "created_at": str(now),
            "data": data
        }, f, indent=2)


# ==================================================
# IDEMPOTENT STAGE GUARD
# ==================================================

import json

def stage_already_completed(chain_id, stage):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT completed_stages FROM chains WHERE chain_id = ?
    """, (chain_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return False

    completed = json.loads(row[0])
    return stage in completed


def mark_stage_completed(chain_id, stage):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT completed_stages FROM chains WHERE chain_id = ?
    """, (chain_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return

    completed = json.loads(row[0])

    if stage not in completed:
        completed.append(stage)

        cursor.execute("""
            UPDATE chains
            SET completed_stages = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE chain_id = ?
        """, (json.dumps(completed), chain_id))

        conn.commit()

    conn.close()
