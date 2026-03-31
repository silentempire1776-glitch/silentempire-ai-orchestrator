import os
import traceback
from openai import OpenAI
from .base import BaseProvider


# ==========================================
# NVIDIA (MOONSHOT / NIM) PROVIDER
# ==========================================

class NvidiaProvider(BaseProvider):

    def __init__(self):
        """
        Initializes NVIDIA provider using Moonshot API key.
        """

        api_key = os.getenv("MOONSHOT_API_KEY")

        if not api_key:
            raise Exception("MOONSHOT_API_KEY is not set")

        # NVIDIA uses OpenAI-compatible SDK with custom base_url
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1"
        )

    # ==========================================
    # MODEL EXECUTION
    # ==========================================

    def run(self, model: str, messages: list, timeout: int):
        """
        Executes NVIDIA model call using OpenAI-compatible endpoint.
        """

        temperature = float(os.getenv("NVIDIA_TEMPERATURE", "0.7"))
        top_p = float(os.getenv("NVIDIA_TOP_P", "0.95"))
        max_tokens = int(os.getenv("NVIDIA_MAX_TOKENS", "8192"))

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=max(timeout or 0, 120),
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p
            )

        except Exception as e:
            print("========== NVIDIA API ERROR ==========")
            print("MODEL:", model)
            print("ERROR TYPE:", type(e).__name__)
            print("ERROR MESSAGE:", str(e))
            traceback.print_exc()
            print("=======================================")
            raise

        if not response.choices:
            raise Exception("NVIDIA returned no choices")

        content = response.choices[0].message.content

        usage = getattr(response, "usage", None)
        tokens_input = getattr(usage, "prompt_tokens", 0) if usage else 0
        tokens_output = getattr(usage, "completion_tokens", 0) if usage else 0

        return {
            "content":       content,
            "output":        content,
            "provider":      "nvidia",
            "model_used":    model,
            "tokens_in":     tokens_input,
            "tokens_out":    tokens_output,
            "tokens_input":  tokens_input,
            "tokens_output": tokens_output,
        }
