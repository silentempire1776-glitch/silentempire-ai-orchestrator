#!/usr/bin/env python3
"""
Perplexity Web Search for Jarvis
Usage: python3 /ai-firm/tools/perplexity_search.py "query"
"""
import json, os, sys, urllib.request, urllib.error

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_KEY", "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")

def search(query):
    body = json.dumps({
        "model": "perplexity/sonar-pro-search",
        "messages": [
            {"role": "system", "content": "You are a focused web search agent for Silent Empire AI. Provide concise, factual, current information. Cite sources where relevant."},
            {"role": "user", "content": query}
        ],
        "max_tokens": 1024,
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://silentempireai.com",
        "X-Title": "Silent Empire Jarvis Search",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.loads(r.read())
            return j["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: perplexity_search.py 'query'"); sys.exit(1)
    print(search(" ".join(sys.argv[1:])))
