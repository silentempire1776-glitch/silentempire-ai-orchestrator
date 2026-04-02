#!/usr/bin/env python3
"""
Silent Empire AI — Elite Prompt Registry
==========================================
Jarvis and the Code Agent query this registry to get structured,
mission-aware prompts for every task type passed to Claude Code.

Claude Code has full VPS filesystem access. These prompts leverage that
by explicitly instructing Claude Code to READ existing files before writing,
save outputs to the correct paths, and verify its own work.

Usage:
    from prompt_registry import get_prompt
    prompt = get_prompt("lead_magnet", context={"topic": "divorce protection"})
"""

import json
import os
from datetime import datetime
from pathlib import Path

# ── Business context ──────────────────────────────────────────────────────────
def _load_business_config() -> dict:
    try:
        path = Path("/srv/silentempire/ai-firm/config/business.json")
        return json.loads(path.read_text())
    except Exception:
        return {}

def _load_agents_config() -> dict:
    try:
        path = Path("/srv/silentempire/ai-firm/config/agents.json")
        return json.loads(path.read_text())
    except Exception:
        return {}

BIZ = _load_business_config()
AGENTS = _load_agents_config()

COMPANY     = BIZ.get("company", {}).get("name", "Silent Empire AI")
PRODUCT     = BIZ.get("product", {}).get("name", "Silent Vault Trust System")
TAGLINE     = BIZ.get("product", {}).get("tagline", "Silent Vault")
PRICE       = BIZ.get("product", {}).get("price_range", "$5K-$25K")
PRIMARY_MKT = BIZ.get("market", {}).get("primary", {})
BRAND_TONE  = BIZ.get("brand", {}).get("tone", "Direct, authoritative, male-coded")
MISSION     = BIZ.get("company", {}).get("mission", "")

# ── Shared preamble injected into every prompt ────────────────────────────────
SHARED_PREAMBLE = f"""
=== SILENT EMPIRE AI — CLAUDE CODE EXECUTION CONTEXT ===

You are operating as the autonomous Code Agent for {COMPANY}.
You have FULL filesystem access to /srv/silentempire/ on this VPS.

BUSINESS MISSION: {MISSION}

PRIMARY PRODUCT: {PRODUCT} ({TAGLINE})
- Irrevocable non-grantor complex discretionary spendthrift dynasty trust
- Asset protection, divorce protection, wealth preservation, legal tax optimization
- Done-with-you implementation service — $5K–$25K per client
- AI-powered speed: 7–10 days vs. 6–18 weeks from attorneys

PRIMARY MARKET:
- 35–55 yr old men, $120K+/year income
- Pain: Fear of losing assets in divorce, lawsuits, economic collapse
- Pain: Tired of paying high taxes
- Desire: Legal, bulletproof protection that operates silently and invisibly
- Sophistication: High — they research before buying

SECONDARY MARKET:
- Men 24–38, college-educated, early wealth builders
- Pain: No protection yet, don't know where to start
- Desire: Get protected before something goes wrong

BRAND VOICE: {BRAND_TONE}
- Speak to men as men — sovereignty, control, legacy, protection
- Never soft, never corporate, never preachy
- Direct statements over hedging
- No motivational fluff — facts, mechanisms, outcomes

=== CRITICAL OPERATING RULES ===
1. NEVER use `with open(path, "w")` on existing files — ALWAYS read first, then use content.replace()
2. ALWAYS backup files before editing: shutil.copy2(target, f"{{target}}.bak.{{timestamp}}")
3. ALWAYS verify after writing — read back and assert expected content exists
4. Save ALL reports to /srv/silentempire/ai-firm/data/reports/[agent]/[YYYY-MM-DD_HH-MM]_[slug].md
5. Report EXACTLY what files were written and what commands were run
6. If a file doesn't exist, say so — never invent contents
7. After writing Python files, run: python3 -m py_compile [file] to check syntax

=== PATH MAPPING ===
Host path:      /srv/silentempire/ai-firm/
Container path: /ai-firm/
Always use HOST paths (/srv/silentempire/) when writing files from Claude Code.

""".strip()


# ── Individual prompt templates ───────────────────────────────────────────────

def prompt_lead_magnet(context: dict = {}) -> str:
    topic    = context.get("topic", "asset protection for high-income men")
    format_  = context.get("format", "PDF guide")
    ts       = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/sales/{ts}_lead-magnet.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: CREATE ELITE LEAD MAGNET ===

Topic: {topic}
Format: {format_}
Save path: {save_path}

You are writing a premium lead magnet for {TAGLINE}.
This document will be given to prospects in exchange for their contact information.
It must be so good they feel they owe us something before we ask for anything.

STRUCTURE (produce ALL sections):

## 1. TITLE (3 options)
Magnetic, specific, outcome-focused. Target primary market pain.
Examples of the format we want:
- "The 7 Assets Divorce Attorneys Target First (And How to Make Them Untouchable)"
- "Why High-Income Men Lose Everything in Divorce — And the One Legal Structure That Stops It"
- "The $0 Tax Strategy Wealthy Men Use to Protect Assets Their Attorneys Don't Know About"

## 2. HOOK / OPEN LOOP (300–500 words)
Open with a specific, visceral scenario the target reader recognizes.
Create an open loop — a burning question that only reading the full guide answers.
NO corporate fluff. NO motivational quotes. Start with the nightmare scenario.

## 3. THE PROBLEM (400–600 words)
Agitate the pain. Specific, real data where possible.
Why traditional solutions (attorneys, prenups, LLCs) fail.
Why being "smart with money" isn't enough.
Make the reader feel the urgency.

## 4. THE MECHANISM (500–800 words)
Explain the core mechanism of the trust solution WITHOUT giving away the implementation.
Name the mechanism. Create intrigue.
Why it works when other things don't.
Why most people have never heard of it.
Include: legal basis, how assets are titled, why creditors can't reach them.

## 5. PROOF / SOCIAL VALIDATION (200–300 words)
Real-world examples (generalized, no names needed).
Statistics on divorce rates, asset seizure, lawsuit frequency for high earners.
Why this is more relevant NOW than ever.

## 6. WHAT'S INSIDE THE FULL SYSTEM (150–200 words)
Tease the full {TAGLINE} implementation without giving it away.
Create desire for the next step.

## 7. CALL TO ACTION (100–150 words)
One clear next step. Specific, not vague.
No "contact us" — "Schedule your Asset Protection Strategy Call."
Urgency without fake scarcity.

WORD COUNT TARGET: 2,000–3,000 words total
TONE: Direct, authoritative, male-coded. Reads like a trusted advisor who has seen everything.
FORBIDDEN: Corporate speak, passive voice, "we believe", motivational quotes, vague promises.

After writing the content, save it to: {save_path}

Use this Python to save (DO NOT use open(path,"w") — write fresh file only since this is new):
```python
from pathlib import Path
Path("{save_path}").parent.mkdir(parents=True, exist_ok=True)
Path("{save_path}").write_text(content)
print(f"Saved: {save_path}")
```

Report: file path, word count, and top 3 strongest hooks produced.
"""


def prompt_sales_copy(context: dict = {}) -> str:
    asset_type = context.get("asset_type", "VSL script")
    funnel_stage = context.get("funnel_stage", "cold traffic")
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/sales/{ts}_sales-copy.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: WRITE ELITE SALES COPY ===

Asset type: {asset_type}
Funnel stage: {funnel_stage}
Save path: {save_path}

You are writing conversion-optimized sales copy for {TAGLINE}.
This copy will directly generate revenue. Every word earns its place.

COPY FRAMEWORK — USE ALL ELEMENTS:

## 1. HEADLINE VARIANTS (5 options)
Pattern interrupt + specific outcome + implied mechanism.
No question headlines. No "Are you tired of...?" openers.
Direct declarative statements that create instant curiosity.

## 2. IDENTITY HOOK (200–300 words)
Who this is for — stated in a way the reader self-selects.
"If you're a man who has built something worth protecting..."
Create identity alignment before making any claim about the product.

## 3. STORY / NARRATIVE (400–600 words)
The transformation arc. Before → mechanism discovered → after.
Specific details make it believable. Vague stories make it feel fake.
The hero of the story is the CLIENT, not us.

## 4. MECHANISM REVEAL (300–400 words)
Name the mechanism. Make it feel proprietary and specific.
Why it's different from what they've tried or heard of.
The unique insight that changes their frame.

## 5. STACK / VALUE PROPOSITION (200–300 words)
What they get. In human terms, not feature terms.
Not "irrevocable trust documentation" — "a legal structure that makes your assets
legally untouchable to divorce attorneys, creditors, and lawsuits."

## 6. OBJECTION HANDLING (400–500 words)
Address the top 5 objections directly:
- "I already have an LLC / prenup"
- "I'm not wealthy enough to need this"
- "Can't I just do this myself?"
- "Is this legal?"
- "Why wouldn't my attorney have told me about this?"

## 7. AUTHORITY / PROOF (200–300 words)
Why we can deliver this. Speed advantage. AI-powered process.
Client outcomes (general, no names). Comparison to attorney cost/time.

## 8. CALL TO ACTION + URGENCY (150–200 words)
Specific next step. Why now matters.
No fake scarcity. Real urgency based on situation (divorce proceedings, lawsuit exposure, tax year).

## 9. P.S. (50–100 words)
Restate the biggest pain and biggest promise. One last CTA.

TONE RULES:
- Never say "our" — say "your protection", "your assets", "your legacy"
- Avoid passive constructions — active, direct verbs only
- No corporate language — write like a trusted friend who happens to be an expert
- Short sentences for impact. Longer sentences for explanation.

Save to: {save_path}
Report: file path, word count, conversion angle used.
"""


def prompt_research_synthesis(context: dict = {}) -> str:
    topic = context.get("topic", "asset protection market 2026")
    depth = context.get("depth", "comprehensive")
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/research/{ts}_research-synthesis.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: ELITE RESEARCH SYNTHESIS ===

Topic: {topic}
Depth: {depth}
Save path: {save_path}

You have access to web search and the VPS filesystem.
Use DuckDuckGo search via: python3 /srv/silentempire/ai-firm/tools/ddg_search.py "query"

RESEARCH PROTOCOL:
1. Run 3–5 targeted searches on the topic
2. Cross-reference findings — note where sources agree and conflict
3. Extract specific data points, statistics, and named competitors
4. Identify patterns the target market cares about

REQUIRED SECTIONS:

## 1. EXECUTIVE SUMMARY (200–300 words)
The 5 most important findings. What this means for {COMPANY}.
Start here — busy founders read this first.

## 2. MARKET LANDSCAPE (400–600 words)
Size, growth, key players, pricing ranges.
Specific numbers, not vague estimates.
Where is money being made right now?

## 3. TARGET AUDIENCE INTELLIGENCE (400–500 words)
Real language the market uses (from forums, Reddit, reviews).
Top fears, top desires, top objections.
What triggers a purchase decision?

## 4. COMPETITIVE ANALYSIS (400–600 words)
Top 5 competitors. For each:
- What they offer
- Their pricing
- Their positioning angle
- Their weakness we can exploit
- Their strength we must acknowledge

## 5. OPPORTUNITY MAP (300–400 words)
Where the gaps are. What the market is underserved on.
Specific angles {TAGLINE} can own that competitors don't.

## 6. CONTENT ANGLES (200–300 words)
10 specific content angles for {TAGLINE} based on this research.
Each angle stated as a hook/headline, not just a topic.

## 7. STRATEGIC RECOMMENDATIONS (200–300 words)
3–5 specific, actionable moves for {COMPANY} based on findings.
Each recommendation tied to specific evidence from research.

Save to: {save_path}
Report: searches run, key data sources, top 3 strategic findings.
"""


def prompt_autonomous_content(context: dict = {}) -> str:
    content_type = context.get("content_type", "social post series")
    platform = context.get("platform", "LinkedIn/Twitter")
    volume = context.get("volume", "5 pieces")
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/sales/{ts}_content-batch.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: AUTONOMOUS CONTENT GENERATION ===

Content type: {content_type}
Platform: {platform}
Volume: {volume}
Save path: {save_path}

Generate {volume} of high-converting {content_type} for {TAGLINE}.
Each piece must be ready to publish — no placeholders, no [INSERT STAT HERE].

CONTENT STANDARDS:
- Every piece targets a specific pain point from the primary market
- Every piece ends with a direction toward the next step (not always hard CTA)
- Mix of: fear-based, aspiration-based, mechanism-based, and social-proof angles
- No vague inspiration — specific, concrete, credible

FOR EACH PIECE INCLUDE:
1. Platform-optimized format (character count, structure)
2. Hook (first line — makes scrolling impossible)
3. Body (the meat — insight, mechanism, or story)
4. CTA or direction
5. 3–5 hashtags if social
6. Internal label: which pain point this targets

CONTENT ANGLES TO ROTATE THROUGH:
- Divorce protection (most acute fear)
- Tax optimization (financial motivation)
- Lawsuit/creditor protection (business owners)
- Legacy/generational wealth (legacy motivation)
- Speed/cost vs. attorneys (competitive advantage)
- Secrecy/privacy (sovereignty angle)
- "You worked too hard" framing (identity/fairness)

Save to: {save_path}
Report: pieces created, pain points targeted, estimated reach by platform.
"""


def prompt_legal_content(context: dict = {}) -> str:
    topic = context.get("topic", "trust compliance and disclaimers")
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/legal/{ts}_legal-analysis.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: LEGAL RISK ANALYSIS FOR CONTENT/MARKETING ===

Topic: {topic}
Save path: {save_path}

You are analyzing legal risk for {COMPANY}'s marketing and content.
This is NOT legal advice — this is risk identification for internal decision-making.

REQUIRED SECTIONS:

## 1. RISK EXPOSURE MAP
Specific claims in our marketing that could create legal exposure.
Rate each: Low / Medium / High risk.

## 2. REQUIRED DISCLAIMERS
Exact disclaimer language needed for website, emails, documents.
Not vague — actual usable disclaimer text.

## 3. CLAIM BOUNDARIES
What we CAN say vs. what we CANNOT say about:
- Tax benefits (specific limits)
- Asset protection guarantees (what can/cannot be promised)
- Legal structure (UPL — unauthorized practice of law risks)
- Speed claims ("7-10 days" — evidence needed)

## 4. JURISDICTION SENSITIVITIES
States where asset protection trusts face additional scrutiny.
Marketing restrictions by state if any.

## 5. HIGH-RISK LANGUAGE TO AVOID
Specific phrases that trigger regulatory or legal risk.
Replacement language for each.

## 6. COMPLIANCE CHECKLIST
10-item checklist for every piece of content before publishing.

## 7. DOCUMENTATION REQUIREMENTS
What records must be kept for each client engagement.
Minimum required paperwork before implementation begins.

Save to: {save_path}
Report: highest-risk items identified, immediate actions required.
"""


def prompt_system_build(context: dict = {}) -> str:
    system = context.get("system", "automation tool")
    specs  = context.get("specs", "")
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/code/{ts}_system-build.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: AUTONOMOUS SYSTEM BUILD ===

System: {system}
Specs: {specs}
Save path: {save_path}

You are building a production system for {COMPANY}.
Full VPS access. Build it completely — no stubs, no TODOs.

BUILD PROTOCOL:
1. READ existing relevant files before writing anything
   - ls /srv/silentempire/ai-firm/tools/ to see existing tools
   - cat relevant files to understand patterns already in use
2. WRITE complete, production-ready implementation
   - Follow patterns from existing tools (see ddg_search.py, telegram.py for style)
   - Include all imports, error handling, logging
   - Use the systemd service pattern for any long-running process
3. VERIFY after writing
   - python3 -m py_compile [file] for Python files
   - Check for obvious logic errors
4. DOCUMENT what was built
   - What the system does
   - How to invoke it
   - What environment variables it needs

EXISTING PATTERNS TO FOLLOW:
- Tool scripts: /srv/silentempire/ai-firm/tools/
- Agent memory: /srv/silentempire/ai-firm/data/memory/agents/[name]/core.md
- Reports: /srv/silentempire/ai-firm/data/reports/[agent]/[ts]_[slug].md
- Systemd services: /etc/systemd/system/[service-name].service

DEPLOYMENT (if needed):
For agents: docker cp [file] [container]:/app/[file] && docker restart [container]
For systemd: systemctl daemon-reload && systemctl enable && systemctl start [service]
For tools: just save to /srv/silentempire/ai-firm/tools/ (shared volume)

Save build report to: {save_path}
Report: files written, verification results, deployment steps taken.
"""


def prompt_morning_briefing(context: dict = {}) -> str:
    date = context.get("date", datetime.now().strftime("%A, %B %d, %Y"))
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/research/{ts}_morning-briefing.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: GENERATE MORNING INTELLIGENCE BRIEFING ===

Date: {date}
Save path: {save_path}

Generate the daily morning briefing for Curtis Proske (Founder, {COMPANY}).
This is delivered via Telegram and Mission Control every morning.
It must be immediately actionable — not a status report, an intelligence brief.

STEPS:
1. Read agent memory files to understand recent activity:
   - ls /srv/silentempire/ai-firm/data/reports/ (check recent reports)
   - cat /srv/silentempire/ai-firm/data/memory/jarvis/core.md
   - cat /srv/silentempire/ai-firm/data/memory/agents/research/core.md
   - cat /srv/silentempire/ai-firm/data/memory/agents/sales/core.md

2. Run 2–3 market intelligence searches:
   - python3 /srv/silentempire/ai-firm/tools/ddg_search.py "asset protection trust news today"
   - python3 /srv/silentempire/ai-firm/tools/ddg_search.py "irrevocable trust divorce protection 2026"

3. Check latest chain reports:
   - ls -t /srv/silentempire/ai-firm/data/reports/chains/*.md | head -3
   - cat the most recent chain report

BRIEFING FORMAT:

# 🧠 Morning Briefing — {date}

## Priority Actions (Top 3 things Curtis should do TODAY)
Each action: specific, measurable, why it matters now.

## Agent Activity Summary
What the agents accomplished in the last 24 hours.
Key outputs produced. Files written. Quality scores.

## Market Intelligence
2–3 relevant market observations from search results.
What's happening in asset protection / trust / wealth management space.
Opportunities or threats to act on.

## Revenue Pipeline Status
Where we are vs. $1K/day target.
What's the bottleneck right now.
One specific action to move revenue today.

## Recommended Agent Dispatches
2–3 agent tasks Jarvis should run TODAY based on gaps identified.
Each stated as a specific instruction ready to dispatch.

Keep it tight. Curtis reads this in 90 seconds. No fluff.

Save to: {save_path}
After saving, output the briefing text directly so it can be sent to Telegram.
"""


def prompt_opportunity_scan(context: dict = {}) -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/research/{ts}_opportunity-scan.md"

    return f"""{SHARED_PREAMBLE}

=== TASK: AUTONOMOUS OPPORTUNITY SCAN ===

Save path: {save_path}

You are Jarvis's intelligence module. Scan for revenue opportunities
that {COMPANY} should act on immediately. No human input needed.

SCAN PROTOCOL:
1. Search for current market activity:
   - python3 /srv/silentempire/ai-firm/tools/ddg_search.py "asset protection trust demand 2026"
   - python3 /srv/silentempire/ai-firm/tools/ddg_search.py "divorce asset protection men high income"
   - python3 /srv/silentempire/ai-firm/tools/ddg_search.py "irrevocable trust competitor pricing 2026"

2. Read existing research for context:
   - ls /srv/silentempire/ai-firm/data/reports/research/ | tail -5
   - cat the most recent research report

3. Read agent memory for recent learnings:
   - cat /srv/silentempire/ai-firm/data/memory/agents/research/core.md
   - cat /srv/silentempire/ai-firm/data/memory/agents/revenue/core.md

OPPORTUNITY REPORT FORMAT:

## High-Priority Opportunities (Act within 48 hours)
For each opportunity:
- What it is (specific, not vague)
- Why now (time-sensitive factor)
- Estimated revenue impact
- Exact agent dispatch needed to execute

## Content Gaps (Produce this week)
Specific content pieces the market is searching for that we don't have.
Each stated as a specific content asset with title.

## Competitive Weaknesses to Exploit
Specific gaps in competitor positioning that we can own immediately.

## Recommended ClickUp Tasks to Create
2–5 specific tasks with: title, description, priority, which agent executes.

Save to: {save_path}
Output the top 3 opportunities as a short summary for Telegram delivery.
"""


# ── Registry ──────────────────────────────────────────────────────────────────

PROMPT_REGISTRY = {
    "lead_magnet":          prompt_lead_magnet,
    "sales_copy":           prompt_sales_copy,
    "research_synthesis":   prompt_research_synthesis,
    "autonomous_content":   prompt_autonomous_content,
    "legal_content":        prompt_legal_content,
    "system_build":         prompt_system_build,
    "morning_briefing":     prompt_morning_briefing,
    "opportunity_scan":     prompt_opportunity_scan,
}


def get_prompt(task_type: str, context: dict = {}) -> str:
    """
    Get an elite structured prompt for Claude Code by task type.

    Args:
        task_type: One of the registered task types
        context: Optional dict with task-specific parameters

    Returns:
        Complete prompt string ready to send to Claude Code bridge
    """
    fn = PROMPT_REGISTRY.get(task_type)
    if not fn:
        available = ", ".join(PROMPT_REGISTRY.keys())
        # Fallback: wrap the task_type as a generic system build
        return f"""{SHARED_PREAMBLE}

=== TASK: {task_type.upper().replace("_", " ")} ===

{context.get("instruction", "Execute this task completely and autonomously.")}

Save any reports to /srv/silentempire/ai-firm/data/reports/code/{datetime.now().strftime("%Y-%m-%d_%H-%M")}_{task_type}.md
Report what files were written and what was accomplished.
"""
    return fn(context)


def list_available() -> list:
    """Return list of available task types."""
    return list(PROMPT_REGISTRY.keys())


def get_preamble() -> str:
    """Return just the shared preamble for custom prompts."""
    return SHARED_PREAMBLE


# ── CLI usage ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 prompt_registry.py <task_type> [context_json]")
        print(f"Available: {', '.join(list_available())}")
        sys.exit(1)

    task = sys.argv[1]
    ctx = {}
    if len(sys.argv) > 2:
        try:
            ctx = json.loads(sys.argv[2])
        except Exception:
            ctx = {"instruction": " ".join(sys.argv[2:])}

    prompt = get_prompt(task, ctx)
    print(prompt)
