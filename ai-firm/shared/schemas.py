from typing import Dict

def create_task(agent: str, task_type: str, payload: Dict):
    return {
        "agent": agent,
        "task_type": task_type,
        "payload": payload
    }

