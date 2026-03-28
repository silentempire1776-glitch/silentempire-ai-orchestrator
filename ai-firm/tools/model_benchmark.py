#!/usr/bin/env python3
"""
Silent Empire Model Health Benchmark — Multi-Provider
Tests NVIDIA, OpenAI, and Anthropic models.
Scores them, assigns best to each agent role, updates .env and DB.
"""
import os, sys, time, json, re, urllib.request, urllib.error
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

NVIDIA_KEY    = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE   = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "").strip()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
API_BASE      = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

AGENT_PROFILES = {
    "jarvis":   {"speed": 0.8, "quality": 0.2},
    "research": {"speed": 0.2, "quality": 0.8},
    "revenue":  {"speed": 0.2, "quality": 0.8},
    "sales":    {"speed": 0.5, "quality": 0.5},
    "growth":   {"speed": 0.4, "quality": 0.6},
    "product":  {"speed": 0.4, "quality": 0.6},
    "legal":    {"speed": 0.1, "quality": 0.9},
    "systems":  {"speed": 0.7, "quality": 0.3},
    "code":     {"speed": 0.3, "quality": 0.7},
    "voice":    {"speed": 0.9, "quality": 0.1},
}

ENV_MAP = {
    "jarvis":   "MODEL_JARVIS_ORCHESTRATOR",
    "research": "MODEL_RESEARCH",
    "revenue":  "MODEL_FINANCIAL_STRATEGY",
    "sales":    "MODEL_MARKETING",
    "growth":   "MODEL_STRATEGIC_PLANNING",
    "product":  "MODEL_CODING",
    "legal":    "MODEL_LEGAL_STRUCTURING",
    "systems":  "MODEL_SYSTEMS",
    "code":     "MODEL_MICRO_CODING",
}

# Models to test per provider
NVIDIA_MODELS = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-8b-instruct",
    "qwen/qwen3.5-397b-a17b",
    "moonshotai/kimi-k2.5",
    "moonshotai/kimi-k2-instruct",
    "moonshotai/kimi-k2-thinking",
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "qwen/qwen3-coder-480b-a35b-instruct",
    "deepseek-ai/deepseek-v3.2",
    "mistralai/mistral-large-3-675b-instruct-2512",
    "mistralai/devstral-2-123b-instruct-2512",
]

OPENAI_MODELS = [
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o-mini",
    "gpt-5",
    "gpt-5.4-2026-03-05",
    "gpt-5.4-mini-2026-03-17",
    "gpt-5.4-nano-2026-03-17",
    "o3-mini-2025-01-31",
    "o4-mini-2025-04-16",
]

ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5",
]


def _post_json(url, headers, body, timeout=25):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def test_nvidia(model):
    r = {"model": model, "provider": "nvidia", "available": False, "latency_ms": 9999}
    if not NVIDIA_KEY:
        r["error"] = "No NVIDIA_API_KEY"; return r
    start = time.time()
    try:
        d = _post_json(
            f"{NVIDIA_BASE}/chat/completions",
            {"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
            {"model": model, "messages": [{"role":"user","content":"OK"}],
             "max_tokens": 5, "temperature": 0},
        )
        r.update({"available": True, "latency_ms": int((time.time()-start)*1000)})
    except Exception as e:
        r["error"] = str(e)[:60]
        r["latency_ms"] = int((time.time()-start)*1000)
    return r


def test_openai(model):
    r = {"model": model, "provider": "openai", "available": False, "latency_ms": 9999}
    if not OPENAI_KEY:
        r["error"] = "No OPENAI_API_KEY"; return r
    start = time.time()
    try:
        d = _post_json(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            {"model": model, "messages": [{"role":"user","content":"OK"}],
             "max_tokens": 5, "temperature": 0},
            timeout=20,
        )
        r.update({"available": True, "latency_ms": int((time.time()-start)*1000)})
    except urllib.error.HTTPError as e:
        r["error"] = f"HTTP {e.code}"
        r["latency_ms"] = int((time.time()-start)*1000)
    except Exception as e:
        r["error"] = str(e)[:60]
        r["latency_ms"] = int((time.time()-start)*1000)
    return r


def test_anthropic(model):
    r = {"model": model, "provider": "anthropic", "available": False, "latency_ms": 9999}
    if not ANTHROPIC_KEY:
        r["error"] = "No ANTHROPIC_API_KEY"; return r
    start = time.time()
    try:
        d = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
             "Content-Type": "application/json"},
            {"model": model, "max_tokens": 5,
             "messages": [{"role":"user","content":"OK"}]},
            timeout=20,
        )
        r.update({"available": True, "latency_ms": int((time.time()-start)*1000)})
    except urllib.error.HTTPError as e:
        r["error"] = f"HTTP {e.code}"
        r["latency_ms"] = int((time.time()-start)*1000)
    except Exception as e:
        r["error"] = str(e)[:60]
        r["latency_ms"] = int((time.time()-start)*1000)
    return r


def score(result, speed_w, quality_w):
    if not result["available"]: return 0.0
    lat = result["latency_ms"]
    speed_score = max(0, min(100, 100 - (lat - 300) / 120))
    quality_score = 75.0
    return round(speed_score * speed_w + quality_score * quality_w, 1)


def main():
    print("=" * 65)
    print("Silent Empire — Multi-Provider Model Health Benchmark")
    print("=" * 65)

    all_jobs = (
        [(m, "nvidia")    for m in NVIDIA_MODELS] +
        [(m, "openai")    for m in OPENAI_MODELS] +
        [(m, "anthropic") for m in ANTHROPIC_MODELS]
    )
    print(f"Testing {len(all_jobs)} models across 3 providers...")
    print()

    results = []
    def test_one(args):
        model, provider = args
        if provider == "nvidia":    return test_nvidia(model)
        if provider == "openai":    return test_openai(model)
        if provider == "anthropic": return test_anthropic(model)

    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(test_one, job): job for job in all_jobs}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            status = f"OK  {r['latency_ms']}ms" if r["available"] else f"FAIL {r.get('error','')[:30]}"
            prov   = r.get("provider","")[:4].upper()
            short  = r["model"].split("/")[-1][:35]
            print(f"  [{prov}] {short:<37} {status}")

    available = [r for r in results if r["available"]]
    print(f"\n{len(available)}/{len(results)} models available")

    # Update health scores in API
    for r in results:
        try:
            body = json.dumps({
                "model": r["model"], "provider": r.get("provider","nvidia"),
                "success": r["available"], "latency_ms": r["latency_ms"],
            }).encode()
            req = urllib.request.Request(
                f"{API_BASE}/metrics/model_health/update",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

    # Assign best model per agent role
    print("\n" + "=" * 65)
    print("ROLE ASSIGNMENTS:")
    print("=" * 65)
    assignments = {}
    for agent, profile in AGENT_PROFILES.items():
        scored = sorted(
            [(r["model"], score(r, profile["speed"], profile["quality"]), r.get("provider","nvidia"))
             for r in available],
            key=lambda x: -x[1]
        )
        if scored:
            best_model, best_score, best_prov = scored[0]
            assignments[agent] = {"model": best_model, "score": best_score,
                                   "provider": best_prov, "latency_ms": next(
                                       r["latency_ms"] for r in results if r["model"]==best_model)}
            short = best_model.split("/")[-1][:30]
            print(f"  {agent:<10} -> [{best_prov:<9}] {short:<30} score={best_score}")

    # Save report
    report = {
        "run_at": datetime.utcnow().isoformat(),
        "availability": {r["model"]: r for r in results},
        "assignments": assignments,
        "providers_tested": ["nvidia", "openai", "anthropic"],
    }
    os.makedirs("/ai-firm/data/reports/systems", exist_ok=True)
    with open("/ai-firm/data/reports/systems/model-benchmark.json", "w") as f:
        json.dump(report, f, indent=2)

    # Post to API
    try:
        body = json.dumps(report).encode()
        req  = urllib.request.Request(
            f"{API_BASE}/metrics/model_benchmark/save",
            data=body, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    # NOTE: .env auto-write disabled — benchmark scoring is latency-only
    # and would overwrite quality-based assignments with fastest model.
    # Use the Models page to manually assign models per agent.
    print("\nNOTE: Model assignments NOT auto-applied (quality assignments preserved)")
    print("To manually apply, use the Agents page dropdowns in Mission Control.")

    print("\nBenchmark complete.")
    print("Restart services to apply:")
    print("  cd /srv/silentempire/ai-firm && docker compose restart jarvis-orchestrator")
    print("  cd /srv/silentempire/app && docker compose up -d --force-recreate worker-default")
    return report


if __name__ == "__main__":
    main()
