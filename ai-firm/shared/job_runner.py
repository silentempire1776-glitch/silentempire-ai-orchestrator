"""
job_runner.py — Shared polling helper for all agents.

Replaces submit_job() + broken/missing wait logic.

Behavior:
  - Polls every 10 seconds
  - No wall-clock timeout on active jobs (supports long tasks like book writing)
  - Raises after 5 min if job never leaves 'pending' (worker never picked it up)
  - Raises immediately on 'failed' status
  - Returns result text string on 'completed'
"""

import os
import re
import time
from typing import Optional
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

POLL_INTERVAL   = 10    # seconds between status checks
PENDING_TIMEOUT = 300   # 5 min — if still pending (never picked up), give up
RUNNING_TIMEOUT = 3600  # 60 min hard cap even for active jobs (books etc.)


def submit_and_wait(agent_name: str, instruction: str) -> str:
    """
    Submit an ai_task job and block until it completes.
    Returns the result as a plain string.
    Raises RuntimeError on failure or true timeout.
    """
    resp = requests.post(
        f"{API_BASE_URL}/jobs",
        json={"type": "ai_task", "payload": {"instruction": instruction, "agent": agent_name}},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    job_id = data.get("job_id") or data.get("id")
    if not job_id:
        raise RuntimeError(f"No job_id returned: {data}")

    print(f"[{agent_name.upper()}] Job created: {job_id}", flush=True)

    started_at   = time.time()
    first_run_at = None

    while True:
        time.sleep(POLL_INTERVAL)

        try:
            r = requests.get(f"{API_BASE_URL}/jobs/{job_id}", timeout=10)
            r.raise_for_status()
            job = r.json()
        except Exception as e:
            print(f"[{agent_name.upper()}] Poll error (will retry): {e}", flush=True)
            continue

        status  = (job.get("status") or "").lower()
        elapsed = time.time() - started_at

        print(f"[{agent_name.upper()}] Job {job_id} status={status} elapsed={elapsed:.0f}s", flush=True)

        if status == "completed":
            result = job.get("result", "")
            if isinstance(result, dict):
                result = (
                    result.get("content") or
                    result.get("text") or
                    result.get("raw_output") or
                    str(result)
                )
            return str(result or "")

        elif status == "failed":
            err = job.get("error_message") or "unknown error"
            raise RuntimeError(f"Job {job_id} failed: {err}")

        elif status in ("pending", "queued", ""):
            if elapsed > PENDING_TIMEOUT:
                raise RuntimeError(
                    f"Job {job_id} stuck in '{status}' for {elapsed:.0f}s — worker may be down"
                )

        elif status == "running":
            if first_run_at is None:
                first_run_at = time.time()
            run_elapsed = time.time() - first_run_at
            if run_elapsed > RUNNING_TIMEOUT:
                raise RuntimeError(
                    f"Job {job_id} running for {run_elapsed:.0f}s — exceeded {RUNNING_TIMEOUT}s hard cap"
                )


def extract_save_path(instruction: str) -> Optional[str]:
    """
    Parse instruction text for a file save path.
    """
    patterns = [
        r'[Ss]ave (?:your (?:report|findings|output) )?to\s+(/[^\s,\.]+\.(?:md|txt|json|html|pdf|py|js))',
        r'[Rr]eport to\s+(/[^\s,\.]+\.(?:md|txt|json|html))',
        r'[Ww]rite (?:it )?to\s+(/[^\s,\.]+\.(?:md|txt|json|html|py))',
        r'[Ss]ave (?:results?|findings?|output|file) (?:in|at)\s+(/[^\s,\.]+\.(?:md|txt|json|html))',
        r'(/ai-firm/data/reports/[^\s,\.]+\.(?:md|txt|json|html))',
    ]
    for pat in patterns:
        m = re.search(pat, instruction)
        if m:
            return m.group(1)
    return None


def write_report(path: str, content: str, agent_name: str) -> bool:
    """
    Write content to path, creating directories as needed.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[{agent_name.upper()}] Report written: {path} ({len(content)} chars)", flush=True)
        return True
    except Exception as e:
        print(f"[{agent_name.upper()}] File write failed {path}: {e}", flush=True)
        return False
