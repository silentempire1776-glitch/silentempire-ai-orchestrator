import os
from openai import OpenAI
from .base import BaseProvider


class OpenAIProvider(BaseProvider):

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise Exception("OPENAI_API_KEY not set")

        self.client = OpenAI(api_key=api_key)

    def run(self, model: str, messages: list, timeout: int = 120):

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=timeout,
        )

        content = response.choices[0].message.content

        tokens_input = response.usage.prompt_tokens
        tokens_output = response.usage.completion_tokens

        return {
            "output": content,
            "provider": "openai",
            "model_used": model,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output
        }
