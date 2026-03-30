import os
import traceback
from database import SessionLocal
from models import ProviderHealth
from ai_engine.providers.openai_provider import OpenAIProvider
from ai_engine.providers.nvidia_provider import NvidiaProvider
from ai_engine.providers.anthropic_provider import AnthropicProvider

PREFERRED_PROVIDER   = os.getenv("PREFERRED_PROVIDER", "nvidia")
MIN_HEALTH_THRESHOLD = float(os.getenv("MIN_HEALTH_THRESHOLD", "0.60"))
FORCE_FREE_MODE      = os.getenv("FORCE_FREE_MODE", "false").lower() == "true"

openai_provider    = OpenAIProvider()
nvidia_provider    = NvidiaProvider()
anthropic_provider = AnthropicProvider()

print("ROUTER MODULE LOADED")
print("ROUTER POLICY → Preferred:", PREFERRED_PROVIDER)
print("ROUTER POLICY → Min Health Threshold:", MIN_HEALTH_THRESHOLD)
print("ROUTER POLICY → Force Free Mode:", FORCE_FREE_MODE)


def get_provider_health(provider_name: str):
    if provider_name == "nvidia":
        return 1.0 if bool(os.getenv("MOONSHOT_API_KEY") or os.getenv("NVIDIA_API_KEY")) else 0.0
    if provider_name == "openai":
        return 1.0 if bool(os.getenv("OPENAI_API_KEY")) else 0.0
    if provider_name == "anthropic":
        return 1.0 if bool(os.getenv("ANTHROPIC_API_KEY")) else 0.0
    return 0.0


def detect_provider(model: str) -> tuple:
    """Returns (provider_name, clean_model_id)"""
    if not isinstance(model, str):
        return ("nvidia", model)

    # Explicit prefix
    if model.startswith("anthropic/") or model.startswith("claude-"):
        return ("anthropic", model.replace("anthropic/", ""))

    if model.startswith("openai/"):
        return ("openai", model.split("/", 1)[1])

    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3") or model.startswith("codex"):
        return ("openai", model)

    if model.startswith("nvidia-nim/"):
        return ("nvidia", model[len("nvidia-nim/"):])

    # vendor/model slug → NVIDIA NIM
    if "/" in model:
        return ("nvidia", model)

    return ("nvidia", model)


def run_model(model: str, messages: list, timeout: int = 120):
    print("RUN_MODEL CALLED WITH:", model)

    provider_name, clean_model = detect_provider(model)
    print("ROUTER: Detected provider:", provider_name, "model:", clean_model)

    health_map = {
        "openai":    get_provider_health("openai"),
        "nvidia":    get_provider_health("nvidia"),
        "anthropic": get_provider_health("anthropic"),
    }
    print("ROUTER HEALTH MAP:", health_map)

    provider_map = {
        "nvidia":    nvidia_provider,
        "openai":    openai_provider,
        "anthropic": anthropic_provider,
    }

    if FORCE_FREE_MODE:
        provider_name = "nvidia"
        print("ROUTER POLICY: FORCE_FREE_MODE active → Using nvidia only")

    primary = provider_map[provider_name]

    # Fail-fast: no silent fallback chain.
    # If the model fails, raise immediately so the error surfaces in chat.
    try:
        result = primary.run(model=clean_model, messages=messages, timeout=timeout)
        result["provider"] = provider_name
        return result
    except Exception as primary_error:
        print(f"PROVIDER ({provider_name}/{clean_model}) FAILED: {primary_error}")
        raise Exception(
            f"Model `{clean_model}` ({provider_name}) failed: {str(primary_error)[:120]}. "
            f"No fallback configured. Check Models page, run benchmark, select working model."
        )
