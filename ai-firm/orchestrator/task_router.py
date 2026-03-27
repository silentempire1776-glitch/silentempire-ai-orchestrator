from shared.redis_bus import publish
from shared.schemas import create_task
import os

# --------------------------------------------------
# CORE AGENT REGISTRY
# --------------------------------------------------

CORE_AGENTS = [
    "revenue",
    "sales",
    "growth",
    "product",
    "research",
    "legal",
    "systems"
]

# --------------------------------------------------
# DOCTRINE LOADER
# --------------------------------------------------

BASE_PATH = "/app"

def load_file(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""

def build_doctrine(agent_name: str) -> dict:
    """
    Loads central executive doctrine + agent identity + agent soul
    and returns structured doctrine payload.
    """

    executive = load_file(f"{BASE_PATH}/shared/doctrine/EXECUTIVE_STACK.md")
    identity = load_file(f"{BASE_PATH}/agents/{agent_name}/IDENTITY.md")
    soul = load_file(f"{BASE_PATH}/agents/{agent_name}/SOUL.md")

    return {
        "executive": executive,
        "identity": identity,
        "soul": soul
    }

# --------------------------------------------------
# TASK DISPATCH (WITH DOCTRINE INJECTION)
# --------------------------------------------------

def dispatch_task(agent: str, task_type: str, payload: dict):
    """
    Creates structured task via schema,
    injects doctrine,
    and publishes to Redis.
    """

    if agent not in CORE_AGENTS:
        raise ValueError(f"Unknown agent: {agent}")

    # Create base task using existing schema
    task = create_task(agent, task_type, payload)

    # Inject doctrine layer
    doctrine = build_doctrine(agent)
    task["doctrine"] = doctrine

    # Publish to agent channel
    publish(f"agent.{agent}", task)
