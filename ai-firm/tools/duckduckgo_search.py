#!/usr/bin/env python3
"""
DuckDuckGo Web Search for Jarvis — Free, no API key needed.
Default search tool. Use for all web searches unless Perplexity is explicitly requested.

Usage: python3 /ai-firm/tools/duckduckgo_search.py "search query"
"""
import sys
import json

def search(query, max_results=5):
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f"No results found for: {query}"
        
        output = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            body  = r.get("body", "")
            href  = r.get("href", "")
            output.append(f"[{i}] {title}\n{body}\nSource: {href}")
        
        return "\n\n".join(output)
    
    except ImportError:
        return "ERROR: duckduckgo_search package not installed. Run: pip install duckduckgo-search"
    except Exception as e:
        return f"Search error: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: duckduckgo_search.py \'query\'")
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    print(search(query))
