import requests
import os

API_BASE = os.getenv("API_BASE_URL", "http://api:8000")

def submit_job(job_type: str, payload: dict, doctrine: str = None):
    if doctrine:
        payload["executive_stack"] = doctrine

    response = requests.post(
        f"{API_BASE}/jobs",
        json={
            "type": job_type,
            "payload": payload
        }
    )
    response.raise_for_status()
    return response.json()
