import os
import traceback

from database import SessionLocal
from models import ProviderHealth

from ai_engine.providers.openai_provider import OpenAIProvider
from ai_engine.providers.nvidia_provider import NvidiaProvider


# ==========================================
# ROUTING POLICY CONFIG
# ==========================================

PREFERRED_PROVIDER = os.getenv("PREFERRED_PROVIDER", "nvidia")
MIN_HEALTH_THRESHOLD = float(os.getenv("MIN_HEALTH_THRESHOLD", "0.60"))

# Hard override: Never use paid provider
FORCE_FREE_MODE = os.getenv("FORCE_FREE_MODE", "false").lower() == "true"


# ==========================================
# PROVIDER REGISTRY
# ==========================================

openai_provider = OpenAIProvider()
nvidia_provider = NvidiaProvider()


# ==========================================
# ROUTER INITIALIZATION LOG
# ==========================================

print("ROUTER MODULE LOADED")
print("ROUTER POLICY → Preferred:", PREFERRED_PROVIDER)
print("ROUTER POLICY → Min Health Threshold:", MIN_HEALTH_THRESHOLD)
print("ROUTER POLICY → Force Free Mode:", FORCE_FREE_MODE)


# ==========================================
# PROVIDER HEALTH LOOKUP
# ==========================================

def get_provider_health(provider_name: str):
    # Fast health: "configured == healthy"
    if provider_name == "nvidia":
        return 1.0 if bool(os.getenv("MOONSHOT_API_KEY")) else 0.0

    if provider_name == "openai":
        return 1.0 if bool(os.getenv("OPENAI_API_KEY")) else 0.0

    return 0.0

# ==========================================
# PROVIDER SELECTION LOGIC
# ==========================================

def choose_primary_provider(model: str):

    health_map = {
        "openai": get_provider_health("openai"),
        "nvidia": get_provider_health("nvidia"),
    }

    print("ROUTER HEALTH MAP:", health_map)

    # ----------------------------------
    # HARD OVERRIDE: FORCE FREE MODE
    # ----------------------------------

    if FORCE_FREE_MODE:
        print("ROUTER POLICY: FORCE_FREE_MODE active → Using nvidia only")
        return "nvidia"

    # ----------------------------------
    # Preferred provider logic
    # ----------------------------------

    preferred_health = health_map.get(PREFERRED_PROVIDER, 1.0)

    if preferred_health >= MIN_HEALTH_THRESHOLD:
        print("ROUTER POLICY: Preferred provider healthy:", PREFERRED_PROVIDER)
        return PREFERRED_PROVIDER

    # ----------------------------------
    # Fallback to healthiest
    # ----------------------------------

    sorted_providers = sorted(
        health_map.items(),
        key=lambda x: x[1],
        reverse=True
    )

    selected = sorted_providers[0][0]

    print("ROUTER POLICY: Preferred below threshold. Healthiest:", selected)

    return selected


# ==========================================
# MODEL ROUTING WITH POLICY + FALLBACK
# ==========================================

def run_model(model: str, messages: list, timeout: int = 120):

    print("RUN_MODEL CALLED WITH:", model)

    # --------------------------------------------------------------
    # AUTHORITATIVE MODEL-ID ROUTING (prevents OpenAI invalid model)
    # --------------------------------------------------------------
    forced_primary = None

    # Normalize OpenClaw prefix if present
    if isinstance(model, str) and model.startswith("nvidia-nim/"):
        model = model[len("nvidia-nim/"):]

    # If expressed as openai/gpt-*, strip prefix and force OpenAI
    if isinstance(model, str) and model.startswith("openai/"):
        forced_primary = "openai"
        model = model.split("/", 1)[1]

    # If plain OpenAI id (gpt-*) force OpenAI
    elif isinstance(model, str) and model.startswith("gpt-"):
        forced_primary = "openai"

    # Any other vendor/model with a slash goes to NVIDIA NIM
    # (qwen/..., moonshotai/..., z-ai/..., google/...)
    elif isinstance(model, str) and "/" in model:
        forced_primary = "nvidia"
    # --------------------------------------------------------------

    # Policy-based selection (kept intact)
    selected_primary = choose_primary_provider(model)

    # Override policy selection when model-id routing requires it
    if forced_primary is not None:
        selected_primary = forced_primary

    if selected_primary == "nvidia":
        primary_provider = nvidia_provider
        fallback_provider = openai_provider
        fallback_model = "gpt-4o"
        print("ROUTER: Using NVIDIA Provider (Primary)")

    else:
        primary_provider = openai_provider
        fallback_provider = nvidia_provider
        fallback_model = "moonshotai/kimi-k2.5"
        print("ROUTER: Using OpenAI Provider (Primary)")

    # ----------------------------------
    # Attempt Primary Execution
    # ----------------------------------

    try:
        return primary_provider.run(
            model=model,
            messages=messages,
            timeout=timeout
        )

    except Exception as primary_error:

        print("========== PRIMARY PROVIDER FAILED ==========")
        print("MODEL:", model)
        print("ERROR TYPE:", type(primary_error).__name__)
        print("ERROR MESSAGE:", str(primary_error))
        print("TRACEBACK:")
        traceback.print_exc()
        print("=============================================")

        # ----------------------------------
        # FORCE_FREE_MODE blocks paid fallback
        # ----------------------------------

        if FORCE_FREE_MODE:
            print("ROUTER POLICY: FORCE_FREE_MODE prevents fallback to OpenAI")
            raise primary_error

        # ----------------------------------
        # Attempt Fallback Provider
        # ----------------------------------

        try:
            print("Attempting Fallback Provider:", fallback_model)

            return fallback_provider.run(
                model=fallback_model,
                messages=messages,
                timeout=timeout
            )

        except Exception as fallback_error:

            print("========== FALLBACK PROVIDER FAILED ==========")
            print("FALLBACK MODEL:", fallback_model)
            print("ERROR TYPE:", type(fallback_error).__name__)
            print("ERROR MESSAGE:", str(fallback_error))
            print("TRACEBACK:")
            traceback.print_exc()
            print("==============================================")

            raise Exception(
                f"Primary and fallback providers failed.\n"
                f"Primary error: {primary_error}\n"
                f"Fallback error: {fallback_error}"
            )
