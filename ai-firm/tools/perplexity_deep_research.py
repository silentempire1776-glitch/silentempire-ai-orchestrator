#!/usr/bin/env python3
"""
Perplexity Deep Research for Jarvis
Use only when explicit deep research is needed (slower, more thorough).
Usage: python3 /ai-firm/tools/perplexity_deep_research.py "topic"
"""
import json, os, sys, urllib.request, urllib.error

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_KEY", "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")

def deep_research(query):
    body = json.dumps({
        "model": "perplexity/sonar-deep-research",
        "messages": [
            {"role": "system", "content": "You are a deep research agent for Silent Empire AI. Perform thorough multi-source research. Surface the most important facts. Use clear structure with headings and bullets."},
            {"role": "user", "content": query}
        ],
        "max_tokens": 4096,
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://silentempireai.com",
        "X-Title": "Silent Empire Jarvis Deep Research",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read())
            return j["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: perplexity_deep_research.py 'topic'"); sys.exit(1)
    print(deep_research(" ".join(sys.argv[1:])))
