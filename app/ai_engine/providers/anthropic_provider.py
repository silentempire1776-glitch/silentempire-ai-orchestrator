import os
import requests

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE    = "https://api.anthropic.com/v1"

class AnthropicProvider:
    def run(self, model: str, messages: list, timeout: int = 300) -> dict:
        if not ANTHROPIC_API_KEY:
            raise Exception("ANTHROPIC_API_KEY not set")

        # Strip anthropic/ prefix if present
        clean_model = model.replace("anthropic/", "")

        headers = {
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
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
            "max_tokens": 4096,
            "messages":   user_messages,
        }
        if system_msg:
            payload["system"] = system_msg

        resp = requests.post(
            f"{ANTHROPIC_BASE}/messages",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage = data.get("usage", {})
        tokens_in  = usage.get("input_tokens",  0)
        tokens_out = usage.get("output_tokens", 0)

        return {
            "content":     content,
            "model_used":  clean_model,
            "provider":    "anthropic",
            "tokens_in":   tokens_in,
            "tokens_out":  tokens_out,
            "tokens_total": tokens_in + tokens_out,
        }
