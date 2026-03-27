import os
import requests
import json

BASE_URL = "https://integrate.api.nvidia.com/v1"
API_KEY = os.getenv("MOONSHOT_API_KEY")

def call_nvidia(model_id, messages, timeout=30, max_tokens=2048):
    url = f"{BASE_URL}/chat/completions"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=timeout
    )

    response.raise_for_status()
    return response.json()
