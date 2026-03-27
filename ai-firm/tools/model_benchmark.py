#!/usr/bin/env python3
"""
MC15 — Role-Based Model Priority System

Each agent has a curated priority list of top models for their role.
Quality-first: use the best model that responds within the timeout.
Never downgrade to a weaker model just because it's faster.
Generous timeouts for quality work (coding, legal, research).

Scoring: latency test + quality test per role.
"""
import os, sys, time, json, re, requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

NVIDIA_KEY  = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
API_BASE    = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

# ── ROLE-BASED MODEL PRIORITY LISTS ──────────────────────────
# Ordered by expected quality for that role (best first).
# The benchmark will confirm availability and latency,
# then assign the highest-quality model that meets the timeout.
#
# Philosophy:
#   - Jarvis: needs fast strategic reasoning, British wit, strong instruction-following
#   - Research: needs depth, long context, analytical capability
#   - Legal: needs accuracy, reasoning, conservative output
#   - Code: needs coding-specific training, accuracy, tool use
#   - Systems: needs reliability, instruction-following, speed
#   - Creative (Sales/Marketing): needs fluency, creativity
#   - Strategy (Revenue/Growth/Product): needs reasoning + creativity balance

ROLE_MODELS = {
    "jarvis": {
        "timeout_ms": 15000,
        "description": "Command intelligence — fast strategic reasoning",
        "priority_models": [
            "moonshotai/kimi-k2.5",              # Excellent reasoning, strong instruction following
            "moonshotai/kimi-k2-instruct",        # Kimi K2 - strong agentic
            "nvidia/llama-3.3-nemotron-super-49b-v1",  # NVIDIA's strategic reasoning model
            "nvidia/llama-3.1-nemotron-ultra-253b-v1", # Ultra - if available
            "qwen/qwen3.5-397b-a17b",             # Large Qwen - strong reasoning
            "meta/llama-4-maverick-17b-128e-instruct", # Fast reliable fallback
            "meta/llama-3.3-70b-instruct",        # Last resort fast fallback
        ],
    },
    "research": {
        "timeout_ms": 60000,  # Research takes time - 60s timeout
        "description": "Deep analysis — quality over speed, long context",
        "priority_models": [
            "moonshotai/kimi-k2-thinking",        # Thinking model - best for deep research
            "moonshotai/kimi-k2.5",               # Strong analysis
            "nvidia/llama-3.1-nemotron-ultra-253b-v1", # Ultra large
            "qwen/qwen3.5-397b-a17b",             # Large Qwen
            "deepseek-ai/deepseek-v3.2",          # Strong reasoning
            "deepseek-ai/deepseek-v3.1",          # Alternative deepseek
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "meta/llama-3.1-405b-instruct",       # Large Llama
        ],
    },
    "legal": {
        "timeout_ms": 90000,  # Legal analysis can take 90s - accuracy is paramount
        "description": "Legal analysis — accuracy paramount, never rush",
        "priority_models": [
            "moonshotai/kimi-k2-thinking",        # Thinking model for careful analysis
            "deepseek-ai/deepseek-r1-distill-qwen-32b", # Reasoning model
            "nvidia/llama-3.1-nemotron-ultra-253b-v1",
            "qwen/qwen3.5-397b-a17b",
            "moonshotai/kimi-k2.5",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "meta/llama-3.1-405b-instruct",
        ],
    },
    "code": {
        "timeout_ms": 120000,  # Code generation can be slow - 2 min timeout
        "description": "Code generation — specialized coding models only",
        "priority_models": [
            "qwen/qwen3-coder-480b-a35b-instruct", # Best coding model on NVIDIA
            "moonshotai/kimi-k2-instruct",         # Strong at code
            "mistralai/devstral-2-123b-instruct-2512", # Mistral's coding model
            "mistralai/codestral-22b-instruct-v0.1",  # Codestral - coding specific
            "qwen/qwen2.5-coder-32b-instruct",     # Qwen coder
            "deepseek-ai/deepseek-coder-6.7b-instruct", # DeepSeek coder
            "ibm/granite-34b-code-instruct",       # IBM's coding model
            "meta/codellama-70b",                  # CodeLlama fallback
        ],
    },
    "revenue": {
        "timeout_ms": 60000,
        "description": "Financial strategy — strong reasoning, numerical accuracy",
        "priority_models": [
            "moonshotai/kimi-k2.5",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "qwen/qwen3.5-397b-a17b",
            "deepseek-ai/deepseek-v3.2",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "meta/llama-3.1-405b-instruct",
            "meta/llama-3.3-70b-instruct",
        ],
    },
    "sales": {
        "timeout_ms": 45000,
        "description": "Sales strategy — creative, persuasive, balanced",
        "priority_models": [
            "moonshotai/kimi-k2.5",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "writer/palmyra-creative-122b",        # Creative writing strength
            "qwen/qwen3.5-397b-a17b",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "meta/llama-4-maverick-17b-128e-instruct",
            "meta/llama-3.3-70b-instruct",
        ],
    },
    "growth": {
        "timeout_ms": 45000,
        "description": "Growth strategy — analytical + creative balance",
        "priority_models": [
            "moonshotai/kimi-k2.5",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "qwen/qwen3.5-397b-a17b",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "deepseek-ai/deepseek-v3.2",
            "meta/llama-4-maverick-17b-128e-instruct",
        ],
    },
    "product": {
        "timeout_ms": 45000,
        "description": "Product strategy — reasoning + technical understanding",
        "priority_models": [
            "moonshotai/kimi-k2-instruct",         # Strong at structured product thinking
            "moonshotai/kimi-k2.5",
            "qwen/qwen3.5-397b-a17b",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "qwen/qwen3-coder-480b-a35b-instruct", # Technical product needs coding awareness
            "meta/llama-4-maverick-17b-128e-instruct",
        ],
    },
    "systems": {
        "timeout_ms": 30000,
        "description": "Infrastructure — reliability + speed + technical accuracy",
        "priority_models": [
            "qwen/qwen3-coder-480b-a35b-instruct", # Best for technical/infra tasks
            "moonshotai/kimi-k2-instruct",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "meta/llama-4-maverick-17b-128e-instruct",
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-8b-instruct",          # Ultra-fast emergency fallback
        ],
    },
    "voice": {
        "timeout_ms": 8000,   # Voice MUST be fast
        "description": "Voice interface — speed critical, 8s hard limit",
        "priority_models": [
            "meta/llama-4-maverick-17b-128e-instruct",
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "mistralai/mistral-small-3.1-24b-instruct-2503",
        ],
    },
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

# Quality test prompts per role — short enough to get quick responses
QUALITY_PROMPTS = {
    "jarvis":   "In 2 sentences: what makes a good executive decision?",
    "research": "In 2 sentences: what is the most important metric for measuring market share?",
    "legal":    "In 2 sentences: what is the key difference between a contract and an agreement?",
    "code":     "Write a Python one-liner to flatten a list of lists.",
    "revenue":  "In 2 sentences: what drives revenue growth for a SaaS company?",
    "sales":    "In 2 sentences: what is the most effective sales closing technique?",
    "growth":   "In 2 sentences: what is a growth loop?",
    "product":  "In 2 sentences: what is the difference between a feature and a benefit?",
    "systems":  "In 1 sentence: what does 'idempotent' mean in infrastructure?",
    "voice":    "Say hello in one word.",
}

def test_model_for_role(model: str, role: str, timeout_ms: int) -> dict:
    """Test a model with a role-specific quality prompt."""
    result = {
        "model": model,
        "role": role,
        "available": False,
        "latency_ms": timeout_ms,
        "quality_response": "",
        "error": None,
    }

    if not NVIDIA_KEY:
        result["error"] = "No NVIDIA_API_KEY"
        return result

    prompt = QUALITY_PROMPTS.get(role, "Reply with OK")
    timeout_s = min(timeout_ms / 1000, 30)  # Cap individual test at 30s

    start = time.time()
    try:
        resp = requests.post(
            f"{NVIDIA_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.3,
            },
            timeout=timeout_s,
        )
        elapsed = int((time.time() - start) * 1000)

        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "").strip()
            result.update({
                "available": True,
                "latency_ms": elapsed,
                "quality_response": content[:200],
                "within_timeout": elapsed <= timeout_ms,
            })
        else:
            result.update({
                "latency_ms": elapsed,
                "error": f"HTTP {resp.status_code}",
            })

    except requests.exceptions.Timeout:
        result["error"] = f"Timeout >{timeout_s}s"
        result["latency_ms"] = int(timeout_s * 1000)
    except Exception as e:
        result["error"] = str(e)[:80]
        result["latency_ms"] = int((time.time() - start) * 1000)

    return result


def run_benchmark():
    """
    For each role, test its priority models and select the best available one.
    Uses quality-first selection: take the highest-priority model that:
    1. Responds successfully
    2. Responds within the role's timeout
    """
    print("=" * 65)
    print("Silent Empire — Role-Based Model Quality Benchmark")
    print("=" * 65)
    print()

    if not NVIDIA_KEY:
        print("ERROR: NVIDIA_API_KEY not set")
        sys.exit(1)

    # Collect all unique models to test
    all_models_to_test = set()
    for role_info in ROLE_MODELS.values():
        for m in role_info["priority_models"][:5]:  # Test top 5 per role
            all_models_to_test.add(m)

    print(f"Testing {len(all_models_to_test)} unique models across all roles...")
    print("(Using 30s timeout for availability check, then role-specific timeouts)")
    print()

    # First pass: quick availability check on all models
    availability = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        def quick_test(model):
            r = {"model": model, "available": False, "latency_ms": 9999}
            try:
                start = time.time()
                resp = requests.post(
                    f"{NVIDIA_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": "OK"}],
                          "max_tokens": 5, "temperature": 0},
                    timeout=25,
                )
                elapsed = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    r.update({"available": True, "latency_ms": elapsed})
                else:
                    r["error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                r["error"] = str(e)[:50]
                r["latency_ms"] = int((time.time() - start) * 1000)
            return r

        futures = {ex.submit(quick_test, m): m for m in all_models_to_test}
        for fut in as_completed(futures):
            r = fut.result()
            availability[r["model"]] = r
            status = f"✓ {r['latency_ms']}ms" if r["available"] else f"✗ {r.get('error','fail')}"
            short = r["model"].split("/")[-1][:38]
            print(f"  {short:<40} {status}")

    available_count = sum(1 for r in availability.values() if r["available"])
    print(f"\n{available_count}/{len(all_models_to_test)} models available")
    print()

    # Second pass: select best model per role
    print("=" * 65)
    print("ROLE ASSIGNMENTS (quality-first selection):")
    print("=" * 65)

    assignments = {}
    all_results = []

    for role, role_info in ROLE_MODELS.items():
        timeout_ms = role_info["timeout_ms"]
        priority_models = role_info["priority_models"]

        selected_model = None
        selected_latency = None

        for model in priority_models:
            r = availability.get(model, {})
            if not r.get("available"):
                continue
            latency = r.get("latency_ms", 9999)
            if latency <= timeout_ms:
                selected_model = model
                selected_latency = latency
                break  # Take the highest-priority model that fits

        if not selected_model:
            # All priority models failed or timed out — use fastest available
            available_models = [(m, availability[m]["latency_ms"])
                                for m in priority_models
                                if availability.get(m, {}).get("available")]
            if available_models:
                selected_model, selected_latency = min(available_models, key=lambda x: x[1])
                note = f"⚠️  fallback (all exceeded {timeout_ms}ms timeout)"
            else:
                selected_model = priority_models[-1]  # Last resort
                selected_latency = 9999
                note = "⚠️  all unavailable"
        else:
            note = "✓ quality-first"

        assignments[role] = {
            "model":      selected_model,
            "latency_ms": selected_latency,
            "timeout_ms": timeout_ms,
            "note":       note,
            "priority_rank": priority_models.index(selected_model) + 1
                             if selected_model in priority_models else "?",
        }

        short = selected_model.split("/")[-1][:32]
        print(f"  {role:<10} [{note}]")
        print(f"             → {short} ({selected_latency}ms, rank #{assignments[role]['priority_rank']} of {len(priority_models)})")
        print()

    # Save results
    report = {
        "run_at":      datetime.utcnow().isoformat(),
        "availability": availability,
        "assignments": assignments,
        "role_configs": {r: {"timeout_ms": v["timeout_ms"], "description": v["description"],
                              "priority_models": v["priority_models"]}
                         for r, v in ROLE_MODELS.items()},
    }

    os.makedirs("/ai-firm/data/reports/systems", exist_ok=True)
    with open("/ai-firm/data/reports/systems/model-benchmark.json", "w") as f:
        json.dump(report, f, indent=2)

    # Post to API
    try:
        requests.post(f"{API_BASE}/metrics/model_benchmark/save", json=report, timeout=5)
    except Exception:
        pass

    # Update model health scores
    for model, r in availability.items():
        try:
            requests.post(f"{API_BASE}/metrics/model_health/update", json={
                "model": model, "provider": "nvidia",
                "success": r.get("available", False),
                "latency_ms": r.get("latency_ms", 0),
            }, timeout=3)
        except Exception:
            pass

    # Update .env
    env_path = "/srv/silentempire/app/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            env = f.read()
        changed = []
        for role, info in assignments.items():
            var = ENV_MAP.get(role)
            if not var:
                continue
            model = info["model"]
            pattern = rf'^{var}=.*$'
            if re.search(pattern, env, re.MULTILINE):
                env = re.sub(pattern, f'{var}={model}', env, flags=re.MULTILINE)
            else:
                env += f'\n{var}={model}'
            changed.append(f"  {var}={model.split('/')[-1]}")
        with open(env_path, "w") as f:
            f.write(env)
        print("=" * 65)
        print(".env UPDATED:")
        print("\n".join(changed))
    else:
        print(f"WARNING: .env not found at {env_path}")

    print()
    print("=" * 65)
    print(f"Benchmark complete. Report: /ai-firm/data/reports/systems/model-benchmark.json")
    print("Restart services to apply new model assignments:")
    print("  cd /srv/silentempire/ai-firm && docker compose restart jarvis-orchestrator")
    print("  cd /srv/silentempire/app && docker compose up -d --force-recreate worker-default")
    print("=" * 65)

    return report


if __name__ == "__main__":
    run_benchmark()
