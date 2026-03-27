import uuid
from shared.redis_bus import publish
from shared.schemas import create_task

# --------------------------------------------------
# DEFAULT DOCTRINE
# --------------------------------------------------

DEFAULT_DOCTRINE = {
    "executive": "Silent Empire Executive Stack",
    "identity": "Elite Strategic Agent",
    "soul": "Relentless precision. Structured value. No fluff."
}

# --------------------------------------------------
# LAUNCH CHAIN
# --------------------------------------------------

def launch_chain(target, product, doctrine=None):

    if doctrine is None:
        doctrine = DEFAULT_DOCTRINE

    payload = {
        "target": target,
        "product": product,
        "chain_id": str(uuid.uuid4())
    }

    task = create_task("research", "offer_stack", payload)
    task["doctrine"] = doctrine

    publish("agent.research", task)

    print("Chain launched successfully.")
