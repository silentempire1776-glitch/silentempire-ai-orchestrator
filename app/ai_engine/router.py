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

    # Fallback chain per provider
    fallback_chain = {
        "nvidia":    [("openai",    "gpt-4.1"),
                      ("anthropic", "claude-sonnet-4-5")],
        "openai":    [("nvidia",    "moonshotai/kimi-k2.5"),
                      ("anthropic", "claude-sonnet-4-5")],
        "anthropic": [("nvidia",    "moonshotai/kimi-k2.5"),
                      ("openai",    "gpt-4.1")],
    }

    if FORCE_FREE_MODE:
        provider_name = "nvidia"
        print("ROUTER POLICY: FORCE_FREE_MODE active → Using nvidia only")

    primary = provider_map[provider_name]

    try:
        result = primary.run(model=clean_model, messages=messages, timeout=timeout)
        result["provider"] = provider_name
        return result
    except Exception as primary_error:
        print(f"PRIMARY PROVIDER ({provider_name}) FAILED: {primary_error}")
        if FORCE_FREE_MODE:
            raise primary_error

        for fallback_provider_name, fallback_model in fallback_chain.get(provider_name, []):
            if health_map.get(fallback_provider_name, 0) < MIN_HEALTH_THRESHOLD:
                continue
            try:
                print(f"Attempting fallback: {fallback_provider_name}/{fallback_model}")
                fallback = provider_map[fallback_provider_name]
                result = fallback.run(model=fallback_model, messages=messages, timeout=timeout)
                result["provider"] = fallback_provider_name
                return result
            except Exception as fe:
                print(f"Fallback {fallback_provider_name} failed: {fe}")
                continue

        raise Exception(f"All providers failed. Primary: {primary_error}")
