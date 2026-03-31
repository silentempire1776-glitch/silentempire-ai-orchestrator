import os
from openai import OpenAI
from .base import BaseProvider
class OpenAIProvider(BaseProvider):
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise Exception("OPENAI_API_KEY not set")
        self.client = OpenAI(api_key=api_key)
    def run(self, model: str, messages: list, timeout: int = 300):
        max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "8192"))
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content
        tokens_in = response.usage.prompt_tokens
        tokens_out = response.usage.completion_tokens
        return {
            "content":       text,
            "output":        text,
            "provider":      "openai",
            "model_used":    model,
            "tokens_in":     tokens_in,
            "tokens_out":    tokens_out,
            "tokens_input":  tokens_in,
            "tokens_output": tokens_out,
        }
