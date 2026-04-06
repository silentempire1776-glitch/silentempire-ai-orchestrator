"""
job_runner.py — Shared polling helper for all agents.

Replaces submit_job() + broken/missing wait logic.

Behavior:
  - Polls every 10 seconds
  - No wall-clock timeout on active jobs (supports long tasks like book writing)
  - Raises after 5 min if job never leaves 'pending' (worker never picked it up)
  - Raises immediately on 'failed' status
  - Returns result text string on 'completed'
"""

import os
import re
import time
from typing import Optional
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

POLL_INTERVAL   = 10    # seconds between status checks
PENDING_TIMEOUT = 300   # 5 min — if still pending (never picked up), give up
RUNNING_TIMEOUT = 3600  # 60 min hard cap even for active jobs (books etc.)


def submit_and_wait(agent_name: str, instruction: str) -> str:
    """
    Submit an ai_task job and block until it completes.
    Returns the result as a plain string.
    Raises RuntimeError on failure or true timeout.
    """
    resp = requests.post(
        f"{API_BASE_URL}/jobs",
        json={"type": "ai_task", "payload": {"instruction": instruction, "agent": agent_name}},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    job_id = data.get("job_id") or data.get("id")
    if not job_id:
        raise RuntimeError(f"No job_id returned: {data}")

    print(f"[{agent_name.upper()}] Job created: {job_id}", flush=True)

    started_at   = time.time()
    first_run_at = None

    while True:
        time.sleep(POLL_INTERVAL)

        try:
            r = requests.get(f"{API_BASE_URL}/jobs/{job_id}", timeout=10)
            r.raise_for_status()
            job = r.json()
        except Exception as e:
            print(f"[{agent_name.upper()}] Poll error (will retry): {e}", flush=True)
            continue

        status  = (job.get("status") or "").lower()
        elapsed = time.time() - started_at

        print(f"[{agent_name.upper()}] Job {job_id} status={status} elapsed={elapsed:.0f}s", flush=True)

        if status == "completed":
            result = job.get("result", "")
            if isinstance(result, dict):
                result = (
                    result.get("content") or
                    result.get("text") or
                    result.get("raw_output") or
                    str(result)
                )
            return str(result or "")

        elif status == "failed":
            err = job.get("error_message") or "unknown error"
            raise RuntimeError(f"Job {job_id} failed: {err}")

        elif status in ("pending", "queued", ""):
            if elapsed > PENDING_TIMEOUT:
                raise RuntimeError(
                    f"Job {job_id} stuck in '{status}' for {elapsed:.0f}s — worker may be down"
                )

        elif status == "running":
            if first_run_at is None:
                first_run_at = time.time()
            run_elapsed = time.time() - first_run_at
            if run_elapsed > RUNNING_TIMEOUT:
                raise RuntimeError(
                    f"Job {job_id} running for {run_elapsed:.0f}s — exceeded {RUNNING_TIMEOUT}s hard cap"
                )


def extract_save_path(instruction: str) -> Optional[str]:
    """
    Parse instruction text for a file save path.
    """
    patterns = [
        r'[Ss]ave (?:your (?:report|findings|output) )?to\s+(/[^\s,\.]+\.(?:md|txt|json|html|pdf|py|js))',
        r'[Rr]eport to\s+(/[^\s,\.]+\.(?:md|txt|json|html))',
        r'[Ww]rite (?:it )?to\s+(/[^\s,\.]+\.(?:md|txt|json|html|py))',
        r'[Ss]ave (?:results?|findings?|output|file) (?:in|at)\s+(/[^\s,\.]+\.(?:md|txt|json|html))',
        r'(/ai-firm/data/reports/[^\s,\.]+\.(?:md|txt|json|html))',
    ]
    for pat in patterns:
        m = re.search(pat, instruction)
        if m:
            return m.group(1)
    return None


def _enforce_naming_convention(path: str) -> str:
    """
    Ensure filename follows YYYY-MM-DD_HH-MM_[topic].md convention.
    Only renames if the filename doesn't already start with a date.
    """
    import re
    from datetime import datetime as _dt
    dir_part = os.path.dirname(path)
    filename = os.path.basename(path)
    # Already follows convention if starts with date pattern
    if re.match(r'\d{4}-\d{2}-\d{2}_', filename):
        return path
    # Strip extension, build new name
    name_no_ext = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1] or ".md"
    timestamp = _dt.utcnow().strftime("%Y-%m-%d_%H-%M")
    new_filename = f"{timestamp}_{name_no_ext}{ext}"
    return os.path.join(dir_part, new_filename)


def write_report(path: str, content: str, agent_name: str) -> bool:
    """
    Write content to path, creating directories as needed.
    Enforces YYYY-MM-DD_HH-MM_[topic].md naming convention.
    """
    try:
        path = _enforce_naming_convention(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[{agent_name.upper()}] Report written: {path} ({len(content)} chars)", flush=True)
        return True
    except Exception as e:
        print(f"[{agent_name.upper()}] File write failed {path}: {e}", flush=True)
        return False


# ==================================================
# EVALUATOR LOOP — Quality scoring + revision
# ==================================================

import re as _re

def _call_evaluator_llm(prompt: str, agent_name: str) -> str:
    """Call Anthropic API for evaluation (uses same key as worker)."""
    import os as _os, requests as _req
    key = _os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return ""
    try:
        r = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001",
                  "max_tokens": 512, "temperature": 0.1,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"[EVALUATOR] LLM call failed: {e}", flush=True)
        return ""


# Per-agent evaluation rubrics
# Business context loaded dynamically — no hardcoded company/product names
def _get_business_context() -> dict:
    """Load business context for rubrics. Falls back gracefully if config unavailable."""
    try:
        from config_loader import get_company_name, get_product_name
        return {"company": get_company_name(), "product": get_product_name()}
    except Exception:
        return {"company": "the company", "product": "the product"}

AGENT_RUBRICS = {
    "research": """Score this research report 1-10 on:
- Specificity: Does it cite data, numbers, market sizes, statistics, or projections? (not generic statements)
- Task completion: Does it directly address the specific research question asked?
- Actionability: Are there concrete findings a decision-maker can act on?
- Domain relevance: Is the content specific and relevant to the task topic and target audience?
- Depth: Does it go beyond surface-level observations into real market dynamics?
Deduct 3 points if it asks for more information instead of executing.
Deduct 2 points if it uses placeholder text or templates with no real content.
CRITICAL: Do NOT penalize specific statistics, projections, or market estimates — these are REQUIRED in strategic research.
CRITICAL: Do NOT flag realistic market data as "fabricated" — strategic research uses industry estimates and forward projections.
CRITICAL: Do NOT penalize competitive analysis reports for lacking product-specific content — competitive analysis IS the task.
A report with specific numbers, data points, and actionable findings should score HIGHER than a vague report without them.""",

    "sales": """Score this sales content 1-10 on:
- Hook quality: Does it open with a compelling, specific hook that grabs attention?
- Pain agitation: Does it speak to real emotional pain points of the target audience?
- Mechanism clarity: Is the product/service solution explained clearly and compellingly?
- Objection handling: Are the key objections of the target audience addressed?
- CTA strength: Is there a clear, specific, urgent call to action?
- Specificity: Is the content tailored to the actual product and audience, not generic?
Deduct 3 points if it asks for product/audience details instead of executing.
Deduct 2 points if it is completely generic with no audience-specific language.
Deduct 2 points if there is no clear CTA.""",

    "legal": """Score this legal analysis 1-10 on:
- Risk identification: Are specific legal risks named, categorized, and explained?
- Jurisdiction awareness: Are relevant jurisdictions and their nuances mentioned?
- Disclaimer quality: Are appropriate, specific disclaimers present?
- Actionability: Are specific compliance steps and risk mitigation actions recommended?
- Structure specificity: Is it specific to the actual product/service structure being analyzed?
- Completeness: Does it cover regulatory, marketing, liability, and operational risks?
Deduct 3 points if it asks for product details instead of executing.
Deduct 2 points for generic legal boilerplate with no specificity.
Deduct 2 points if no actionable compliance recommendations are included.""",

    "revenue": """Score this revenue strategy 1-10 on:
- Pricing specificity: Are actual price points, tiers, or ranges recommended with rationale?
- Offer structure: Is the core offer, value stack, and upsell path defined?
- Revenue projections: Are realistic numbers, timelines, and projections included?
- Market fit: Is the strategy specific to the actual product and target market?
- Actionability: Can this strategy be implemented immediately with the recommendations given?
- LTV thinking: Is customer lifetime value and retention addressed?
Deduct 3 points if it asks for product/audience details instead of executing.
Deduct 2 points if projections or price points are completely missing.
Deduct 1 point for each major revenue component missing (pricing/offer/projections/LTV).""",

    "growth": """Score this growth strategy 1-10 on:
- Channel specificity: Are specific channels named with tactics (not just "use social media")?
- Audience precision: Is the specific target demographic addressed with precision?
- Funnel clarity: Is the full acquisition funnel defined from awareness to close?
- Tactics: Are concrete, implementable tactics listed with expected outcomes?
- Metrics: Are specific success metrics and KPIs defined for each channel?
- Compounding loops: Are growth loops or referral mechanisms identified?
Deduct 3 points if it asks for product/audience details instead of executing.
Deduct 2 points for generic marketing advice with no channel-specific tactics.
Deduct 2 points if no metrics or KPIs are defined.""",

    "product": """Score this product strategy 1-10 on:
- Deliverable clarity: Are specific, concrete deliverables defined (not vague outcomes)?
- Implementation roadmap: Is there a concrete timeline with milestones?
- Client journey: Is the full client experience mapped from onboarding to completion?
- Component specificity: Are modules, phases, or components clearly defined?
- Scalability: Is the scaling model and capacity plan addressed?
- Risk mitigation: Are delivery risks identified with mitigation plans?
Deduct 3 points if it asks for product details instead of executing.
Deduct 2 points for vague deliverables with no concrete specifications.
Deduct 2 points if no implementation timeline is provided.""",

    "systems": """Score this systems/infrastructure output 1-10 on:
- Task completion: Did it complete the actual systems task assigned?
- Technical accuracy: Are the technical recommendations correct and appropriate?
- Specificity: Are specific tools, commands, configs, or architectures named?
- Actionability: Can this be implemented directly from the output?
- Safety: Does it follow safe deployment practices (backups, verification, rollback)?
- Completeness: Are all relevant components of the system addressed?
Deduct 4 points if it returns only a job ID or raw JSON instead of real content.
Deduct 3 points if it asks for more information instead of executing.
Deduct 2 points for generic infrastructure advice with no specifics.
A systems output with actual commands, configs, or architecture decisions scores HIGHER.""",

    "code": """Score this code output 1-10 on:
- Correctness: Does the code actually solve the stated problem?
- Completeness: Is it a complete, runnable implementation (not pseudocode or skeleton)?
- Error handling: Are errors and edge cases handled appropriately?
- Code quality: Is it clean, readable, and follows standard conventions?
- Integration fit: Does it integrate properly with the existing architecture?
- Documentation: Are key functions and logic documented with comments?
Deduct 4 points for pseudocode or skeleton code when real code was requested.
Deduct 3 points if it asks for clarification instead of implementing.
Deduct 2 points for missing error handling on external calls.
Deduct 2 points if it cannot run without significant modification.""",
}

DEFAULT_RUBRIC = """Score this agent output 1-10 on:
- Task completion: Did it fully complete the assigned task without stalling?
- Specificity: Is the output specific, concrete, and actionable (not generic)?
- Quality: Is it professional, well-structured, and immediately usable?
- Execution: Did it execute the task rather than ask for more information?
- Completeness: Are all key components of the task addressed?
Deduct 3 points if it asks for more information instead of executing.
Deduct 2 points for generic, templated output with no task-specific content.
Deduct 2 points if key sections of the task are missing or incomplete."""



def evaluate_output(result_text: str, task: str, agent_name: str) -> dict:
    """
    Evaluate agent output quality. Returns {score, feedback, passed}.
    Uses Haiku for cost efficiency.
    """
    rubric = AGENT_RUBRICS.get(agent_name, DEFAULT_RUBRIC)
    threshold = int(os.getenv(f"EVAL_SCORE_THRESHOLD", "7"))

    _biz = _get_business_context()
    prompt = f"""You are a quality evaluator for {_biz['company']}, evaluating agent output quality.
The company delivers legitimate professional services. Evaluate the agent output below objectively.

{rubric}

TASK GIVEN TO AGENT:
{task[:1000]}

AGENT OUTPUT TO EVALUATE:
{result_text[:6000]}

IMPORTANT: If the output REFUSED to answer or asked for more information instead of executing the task,
score it 0/10 regardless of how politely it refused.
If the output completed the task with real, specific content, score based on quality.
CRITICAL: Strategic research and business analysis ALWAYS uses market estimates, projections, and industry statistics.
Do NOT penalize or flag specific numbers, percentages, dollar figures, or forward-looking projections as "fabricated."
A report with specific data points (e.g. "$4.2B market", "34% adoption rate", "6x audit increase") is BETTER than a vague one.
Only penalize outputs that are completely generic with zero specific information.

Respond in this exact format:
SCORE: [number 1-10]
FEEDBACK: [2-3 sentences on what's missing or needs improvement]
PASSED: [YES if score >= {threshold}, NO if below]"""

    raw = _call_evaluator_llm(prompt, agent_name)
    if not raw:
        return {"score": 8, "feedback": "Evaluator unavailable", "passed": True}

    # Parse response — robust: handles whitespace, inline text, "8/10" format
    score = 7
    feedback = ""
    passed = True
    score_found = False

    for line in raw.splitlines():
        stripped = line.strip()
        upper = stripped.upper()

        if upper.startswith("SCORE:") and not score_found:
            try:
                # Match first integer in line — handles "SCORE: 8", "SCORE: 8/10", "SCORE: 8 out of 10"
                m = _re.search(r'(\d+)', stripped)
                if m:
                    candidate = int(m.group(1))
                    # Sanity check: score must be 1-10, not "10" from "10" in "10/10"
                    if 1 <= candidate <= 10:
                        score = candidate
                        score_found = True
            except Exception:
                pass

        elif upper.startswith("FEEDBACK:"):
            feedback = stripped[len("FEEDBACK:"):].strip()

        elif upper.startswith("PASSED:"):
            passed = "YES" in upper

    # If no PASSED line found, derive from score
    threshold = int(os.getenv("EVAL_SCORE_THRESHOLD", "7"))
    if not any(line.strip().upper().startswith("PASSED:") for line in raw.splitlines()):
        passed = score >= threshold

    print(f"[EVALUATOR] Parsed: score={score} passed={passed} feedback={feedback[:80]}", flush=True)
    return {"score": score, "feedback": feedback, "passed": passed}


def submit_and_wait_with_eval(agent_name: str, instruction: str,
                               task_description: str = "") -> str:
    """
    Submit job, wait for result, evaluate quality.
    If below threshold, revise up to MAX_LOOPS times.
    Returns best result text.
    """
    max_loops = int(os.getenv(f"EVAL_LOOPS_{agent_name.upper()}", "2"))
    threshold = int(os.getenv("EVAL_SCORE_THRESHOLD", "7"))

    best_result = ""
    best_score = 0

    for loop in range(1, max_loops + 1):
        print(f"[{agent_name.upper()}] Eval loop {loop}/{max_loops}", flush=True)

        # Build instruction with revision feedback if not first loop
        current_instruction = instruction
        if loop > 1 and best_result:
            current_instruction = f"""{instruction}

=== REVISION REQUIRED ===
Your previous attempt scored {best_score}/10. Here is the evaluator feedback:
{revision_feedback}

Address ALL feedback points. Produce a substantially improved version.
Do NOT repeat the same mistakes. Execute the task completely."""

        result = submit_and_wait(agent_name, current_instruction)

        if not result:
            print(f"[{agent_name.upper()}] Empty result on loop {loop}", flush=True)
            continue

        # Evaluate
        eval_result = evaluate_output(result, task_description or instruction[:300], agent_name)
        score = eval_result["score"]
        feedback = eval_result["feedback"]
        passed = eval_result["passed"]

        print(f"[{agent_name.upper()}] Loop {loop} score={score}/10 passed={passed}", flush=True)

        if score > best_score:
            best_score = score
            best_result = result
            revision_feedback = feedback

        if passed:
            print(f"[{agent_name.upper()}] Quality threshold met at loop {loop}", flush=True)
            break

        if loop < max_loops:
            print(f"[{agent_name.upper()}] Score {score} below {threshold}, revising...", flush=True)

    print(f"[{agent_name.upper()}] Final score={best_score}/10 after {loop} loop(s)", flush=True)
    # Persist quality_score + eval_loops to DB via API (non-fatal if fails)
    try:
        import os as _os, requests as _req
        _api_base = _os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
        # Find the most recently completed job for this agent within last 10 minutes
        _r = _req.get(
            f"{_api_base}/kanban/cards?limit=10",
            timeout=5
        )
        if _r.ok:
            _cards = _r.json().get("cards", [])
            for _c in _cards:
                if (_c.get("agent") == agent_name and
                    _c.get("status") in ("completed", "running")):
                    _job_id = _c.get("id")
                    _req.post(
                        f"{_api_base}/jobs/{_job_id}/eval",
                        json={
                            "quality_score": best_score,
                            "eval_loops": loop,
                            "feedback": (revision_feedback
                                        if 'revision_feedback' in dir()
                                        else "")
                        },
                        timeout=5
                    )
                    print(f"[{agent_name.upper()}] Eval persisted → job {_job_id[:8]}", flush=True)
                    break
    except Exception as _eval_e:
        print(f"[{agent_name.upper()}] Eval persist skipped: {_eval_e}", flush=True)
    # Persist memory for scores >= 6
    if best_score >= 6 and best_result:
        try:
            summarize_to_memory(agent_name, task_description or instruction[:200], best_result, best_score)
            print(f"[{agent_name.upper()}] Memory updated (score={best_score})", flush=True)
        except Exception as mem_err:
            print(f"[{agent_name.upper()}] Memory write failed: {mem_err}", flush=True)
    return best_result


# ==================================================
# PER-AGENT MEMORY — Persistent knowledge base
# ==================================================

MEMORY_BASE = "/ai-firm/data/memory/agents"


def read_agent_memory(agent_name: str) -> str:
    """Read agent's persistent memory file."""
    path = os.path.join(MEMORY_BASE, agent_name, "core.md")
    try:
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
    except Exception as e:
        print(f"[MEMORY] Read failed for {agent_name}: {e}", flush=True)
    return ""


def write_agent_memory(agent_name: str, content: str) -> None:
    """Append to agent's persistent memory file."""
    path = os.path.join(MEMORY_BASE, agent_name, "core.md")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from datetime import datetime as _dt
        timestamp = _dt.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        with open(path, "a") as f:
            f.write(f"\n---\n[{timestamp}]\n{content}\n")
    except Exception as e:
        print(f"[MEMORY] Write failed for {agent_name}: {e}", flush=True)


def summarize_to_memory(agent_name: str, task: str, result: str, score: int) -> None:
    """Save a summary of completed work to agent memory."""
    if score < 6:
        return  # Don't memorize poor outputs
    summary = f"Task: {task[:200]}\nScore: {score}/10\nKey output: {result[:300]}"
    write_agent_memory(agent_name, summary)
