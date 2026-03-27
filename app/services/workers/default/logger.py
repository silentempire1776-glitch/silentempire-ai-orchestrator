import json
import socket
import datetime
import uuid
import os

WORKER_ID = socket.gethostname()
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")


def log_event(event_type, **kwargs):
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "event": event_type,
        "worker_id": WORKER_ID,
        "environment": ENVIRONMENT,
    }

    payload.update(kwargs)

    print(json.dumps(payload), flush=True)
