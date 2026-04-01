import os
import requests

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE    = "https://api.anthropic.com/v1"

# Models that support prompt caching (extended-context and standard claude models)
CACHE_SUPPORTED_MODELS = {
    "claude-opus-4-5",
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-5",
    "claude-sonnet-4-5-20251022",
    "claude-haiku-4-5",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
}

class AnthropicProvider:
    def run(self, model: str, messages: list, timeout: int = 300) -> dict:
        if not ANTHROPIC_API_KEY:
            raise Exception("ANTHROPIC_API_KEY not set")

        # Strip anthropic/ prefix if present
        clean_model = model.replace("anthropic/", "")

        headers = {
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta":    "prompt-caching-2024-07-31",
            "Content-Type":      "application/json",
        }

        # Separate system message from user messages
        system_msg = ""
        user_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "")
            else:
                user_messages.append({"role": m["role"], "content": m["content"]})

        if not user_messages:
            user_messages = [{"role": "user", "content": "Hello"}]

        payload = {
            "model":      clean_model,
            "max_tokens": 8192,
            "messages":   user_messages,
        }

        # Apply prompt caching to system prompt for supported models
        # Cache requires min 1024 tokens — doctrine easily clears this
        if system_msg:
            use_cache = clean_model in CACHE_SUPPORTED_MODELS
            if use_cache:
                payload["system"] = [
                    {
                        "type": "text",
                        "text": system_msg,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                payload["system"] = system_msg

        import time
        RETRY_STATUSES = {529, 503}
        MAX_ATTEMPTS   = 3
        BACKOFF_S      = 10

        resp = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            resp = requests.post(
                f"{ANTHROPIC_BASE}/messages",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if resp.status_code not in RETRY_STATUSES:
                break
            if attempt < MAX_ATTEMPTS:
                print(
                    f"[ANTHROPIC] {resp.status_code} on attempt {attempt}/{MAX_ATTEMPTS} "
                    f"— retrying in {BACKOFF_S}s",
                    flush=True,
                )
                time.sleep(BACKOFF_S)
            else:
                print(
                    f"[ANTHROPIC] {resp.status_code} on attempt {attempt}/{MAX_ATTEMPTS} "
                    f"— giving up",
                    flush=True,
                )

        resp.raise_for_status()
        data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage = data.get("usage", {})
        tokens_in              = usage.get("input_tokens",                0)
        tokens_out             = usage.get("output_tokens",               0)
        cache_creation_tokens  = usage.get("cache_creation_input_tokens", 0)
        cache_read_tokens      = usage.get("cache_read_input_tokens",     0)

        return {
            "content":               content,
            "model_used":            clean_model,
            "provider":              "anthropic",
            "tokens_in":             tokens_in,
            "tokens_out":            tokens_out,
            "tokens_total":          tokens_in + tokens_out,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens":     cache_read_tokens,
        }
