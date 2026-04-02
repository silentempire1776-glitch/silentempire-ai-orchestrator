#!/usr/bin/env python3
"""
Silent Empire AI — Jarvis Heartbeat / Autonomy Engine
======================================================
Reads autonomy_config.json on EVERY cycle.
Edit the config file — changes take effect within one heartbeat interval.
No code changes, no redeploys needed.

Runs as a background thread inside jarvis-orchestrator.
Provides:
  - Morning intelligence briefing (configurable interval)
  - Opportunity scan (configurable interval)  
  - Standard proactive status update (configurable interval)
  - Autonomous agent dispatch (configurable, off by default)
"""

import json
import os
import time
import uuid
import subprocess
from datetime import datetime
from pathlib import Path

import requests

# ── Config loader ─────────────────────────────────────────────────────────────

CONFIG_PATH = Path("/ai-firm/config/autonomy_config.json")
BUSINESS_PATH = Path("/ai-firm/config/business.json")

def load_config() -> dict:
    """Load autonomy config. Falls back to safe defaults if file missing."""
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        print(f"[HEARTBEAT] Config load failed ({e}), using defaults.", flush=True)
        return {
            "autonomy": {"enabled": True},
            "intervals": {
                "heartbeat_seconds": 1800,
                "morning_briefing_hours": 6,
                "opportunity_scan_hours": 8,
                "status_update_hours": 2,
                "startup_delay_seconds": 120,
            },
            "morning_briefing": {"enabled": True, "deliver_to_telegram": True},
            "opportunity_scan": {"enabled": True, "deliver_to_telegram": True},
            "status_update": {"enabled": True},
            "autonomous_dispatch": {"enabled": False},
            "claude_code": {
                "bridge_url": "http://172.18.0.1:9999",
                "timeout_seconds": 180,
                "work_dir": "/srv/silentempire",
            },
        }

def load_business() -> dict:
    try:
        return json.loads(BUSINESS_PATH.read_text())
    except Exception:
        return {}

# ── API helpers ───────────────────────────────────────────────────────────────

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

def get_active_session() -> str:
    """Get most recently active Mission Control session ID."""
    try:
        resp = requests.get(f"{API_BASE_URL}/sessions", timeout=5)
        if resp.ok:
            sessions = resp.json()
            if sessions and isinstance(sessions, list):
                return sessions[0].get("id", "")
    except Exception:
        pass
    return ""


def write_to_session(session_id: str, content: str, label: str = "Autonomy") -> None:
    """Write a message to Mission Control session."""
    if not session_id:
        return
    try:
        sd = requests.get(f"{API_BASE_URL}/sessions/{session_id}", timeout=5)
        if not sd.ok:
            return
        existing = sd.json()
        messages = existing.get("messages", [])
        messages.append({
            "id":        str(uuid.uuid4())[:8],
            "role":      "jarvis",
            "content":   content,
            "timestamp": datetime.utcnow().isoformat(),
            "mode":      "jarvis",
        })
        requests.put(
            f"{API_BASE_URL}/sessions/{session_id}",
            json={"messages": messages},
            timeout=5
        )
    except Exception as e:
        print(f"[HEARTBEAT] Session write failed: {e}", flush=True)


def send_telegram(message: str) -> None:
    """Send message to Telegram via the tools/telegram.py script."""
    try:
        result = subprocess.run(
            ["python3", "/ai-firm/tools/telegram.py", message[:4000]],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            print(f"[HEARTBEAT] Telegram send failed: {result.stderr[:200]}", flush=True)
    except Exception as e:
        print(f"[HEARTBEAT] Telegram error: {e}", flush=True)


def call_claude_code(prompt: str, cfg: dict) -> dict:
    """Call Claude Code bridge with config-driven URL and timeout."""
    cc_cfg = cfg.get("claude_code", {})
    bridge_url = cc_cfg.get("bridge_url", "http://172.18.0.1:9999")
    timeout    = cc_cfg.get("timeout_seconds", 180)
    work_dir   = cc_cfg.get("work_dir", "/srv/silentempire")

    try:
        resp = requests.post(
            f"{bridge_url}/run",
            json={"prompt": prompt, "work_dir": work_dir, "timeout": timeout},
            timeout=timeout + 20
        )
        return resp.json()
    except Exception as e:
        return {"success": False, "output": str(e)}


# ── Morning briefing ──────────────────────────────────────────────────────────

def run_morning_briefing(session_id: str, cfg: dict) -> None:
    """Generate and deliver morning intelligence briefing."""
    bc_cfg   = cfg.get("morning_briefing", {})
    biz      = load_business()
    company  = biz.get("company", {}).get("name", "Silent Empire AI")
    product  = biz.get("product", {}).get("tagline", "Silent Vault")
    target   = cfg.get("business_context", {}).get("revenue_target_daily", 1000)
    searches = bc_cfg.get("searches", [
        "irrevocable trust asset protection 2026",
        "divorce asset protection high income men",
    ])
    sections = bc_cfg.get("sections", [
        "Priority Actions Today",
        "Agent Activity (Last 24h)",
        "Market Intelligence",
        "Revenue Status",
        "Recommended Dispatches",
    ])

    date_str  = datetime.now().strftime("%A, %B %d, %Y")
    ts        = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/research/{ts}_morning-briefing.md"

    search_cmds = "\n".join(
        f'   python3 /srv/silentempire/ai-firm/tools/ddg_search.py "{q}"'
        for q in searches
    )
    sections_list = "\n".join(f"## {s}" for s in sections)

    prompt = f"""Generate the morning intelligence briefing for the Founder of {company}.
Date: {date_str}

Execute these steps IN ORDER:
1. Check recent reports:
   ls /srv/silentempire/ai-firm/data/reports/research/ 2>/dev/null | tail -5
   ls /srv/silentempire/ai-firm/data/reports/sales/ 2>/dev/null | tail -3

2. Read Jarvis memory:
   cat /srv/silentempire/ai-firm/data/memory/jarvis/core.md 2>/dev/null | tail -40

3. Run market searches:
{search_cmds}

4. Check latest chain reports:
   ls -t /srv/silentempire/ai-firm/data/reports/chains/*.md 2>/dev/null | head -3

Now write the briefing with these sections:
{sections_list}

REVENUE TARGET: ${target}/day

RULES:
- Every action in "Priority Actions Today" must be specific and measurable
- "Revenue Status" must be honest — not cheerful if we're not there yet
- "Recommended Dispatches" must name agent + exact instruction ready to run
- Tight. 90-second read. No fluff. No generic statements.

Save to: {save_path}
Then output ONLY the briefing text (no preamble) for Telegram delivery."""

    print(f"[HEARTBEAT] Running morning briefing...", flush=True)
    result = call_claude_code(prompt, cfg)

    if result.get("success") and result.get("output"):
        output = result["output"].strip()
        header = f"🧠 Morning Briefing — {date_str}\n\n"
        full_msg = header + output

        if bc_cfg.get("deliver_to_telegram", True):
            send_telegram(full_msg[:4000])

        if bc_cfg.get("deliver_to_mission_control", True) and session_id:
            write_to_session(session_id, f"**[Morning Briefing — {date_str}]**\n\n{output[:3000]}")

        print(f"[HEARTBEAT] Morning briefing delivered.", flush=True)
    else:
        print(f"[HEARTBEAT] Morning briefing failed: {result.get('output','?')[:300]}", flush=True)


# ── Opportunity scan ──────────────────────────────────────────────────────────

def run_opportunity_scan(session_id: str, cfg: dict) -> None:
    """Run autonomous market opportunity scan."""
    sc_cfg   = cfg.get("opportunity_scan", {})
    biz      = load_business()
    product  = biz.get("product", {}).get("tagline", "Silent Vault")
    searches = sc_cfg.get("searches", [
        "asset protection trust market demand 2026",
        "irrevocable trust competitors pricing",
        "divorce protection high income men",
    ])
    sections = sc_cfg.get("output_sections", [
        "Top 3 Opportunities (act within 48 hours)",
        "Content Gaps to Fill This Week",
        "Competitive Weaknesses to Exploit",
    ])

    ts        = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_path = f"/srv/silentempire/ai-firm/data/reports/research/{ts}_opportunity-scan.md"

    search_cmds = "\n".join(
        f'python3 /srv/silentempire/ai-firm/tools/ddg_search.py "{q}"'
        for q in searches
    )
    sections_fmt = "\n".join(f"## {s}" for s in sections)

    prompt = f"""Run an autonomous opportunity scan for {product}.

Execute all searches:
{search_cmds}

Also read recent research context:
ls /srv/silentempire/ai-firm/data/reports/research/ | tail -5

Save a focused opportunity report to: {save_path}

Report format:
# Opportunity Scan — {ts}
{sections_fmt}

For "Top 3 Opportunities" — each entry must have:
- What it is (specific, not vague)
- Why NOW (time-sensitive factor)
- Estimated revenue impact
- Exact agent + instruction to execute it

For "Content Gaps" — state each as a specific content title the market is searching for.

After saving, output ONLY a 3-bullet summary (max 200 chars each bullet) for Telegram delivery."""

    print(f"[HEARTBEAT] Running opportunity scan...", flush=True)
    result = call_claude_code(prompt, cfg)

    if result.get("success") and result.get("output"):
        output = result["output"].strip()
        full_msg = f"🔍 Opportunity Scan\n\n{output}"

        if sc_cfg.get("deliver_to_telegram", True):
            send_telegram(full_msg[:4000])

        if sc_cfg.get("deliver_to_mission_control", True) and session_id:
            write_to_session(session_id, f"**[Opportunity Scan — {ts}]**\n\n{output[:3000]}")

        print(f"[HEARTBEAT] Opportunity scan complete.", flush=True)
    else:
        print(f"[HEARTBEAT] Opportunity scan failed: {result.get('output','?')[:300]}", flush=True)


# ── Standard status update ────────────────────────────────────────────────────

def run_status_update(session_id: str, cfg: dict) -> None:
    """Standard proactive status check — delegates to _send_proactive_update in main."""
    # Import and call the existing function from main.py
    # This keeps the status update logic in one place
    try:
        from orchestrator.main import _send_proactive_update
        _send_proactive_update()
        print(f"[HEARTBEAT] Status update sent.", flush=True)
    except Exception as e:
        print(f"[HEARTBEAT] Status update failed: {e}", flush=True)


# ── Main heartbeat loop ───────────────────────────────────────────────────────

_HEARTBEAT_RUNNING = False  # Global flag — only one heartbeat loop per process

def hybrid_autonomy_loop() -> None:
    """
    Main autonomy loop. Reads config on every cycle.
    Edit autonomy_config.json — changes take effect within one heartbeat interval.
    Includes global flag to prevent duplicate loops within same process.
    """
    global _HEARTBEAT_RUNNING
    if _HEARTBEAT_RUNNING:
        print("[HEARTBEAT] Already running in this process — skipping duplicate.", flush=True)
        return
    _HEARTBEAT_RUNNING = True

    # Load config once for startup delay
    cfg = load_config()
    startup_delay = cfg.get("intervals", {}).get("startup_delay_seconds", 300)
    print(f"[HEARTBEAT] Autonomy engine starting. Startup delay: {startup_delay}s", flush=True)
    time.sleep(startup_delay)

    # PATCH4_REDIS_TIMERS
    # Timer tracking — Redis-backed so restarts don't re-trigger immediately
    def _load_ts(key: str) -> float:
        """Load last-fired timestamp from Redis, default to now-minus-1-hour."""
        try:
            import redis as _r3
            _rc3 = _r3.from_url(
                os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
                decode_responses=True
            )
            val = _rc3.get(f"heartbeat:last_fired:{key}")
            if val:
                return float(val)
        except Exception:
            pass
        # Default: pretend it fired 1 hour ago — safe delay regardless of interval
        return time.time() - 3600

    def _save_ts(key: str, ts: float) -> None:
        try:
            import redis as _r4
            _rc4 = _r4.from_url(
                os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"),
                decode_responses=True
            )
            _rc4.set(f"heartbeat:last_fired:{key}", str(ts), ex=86400 * 7)
        except Exception:
            pass

    _last_briefing   = _load_ts("briefing")
    _last_opp_scan   = _load_ts("opp_scan")
    _last_status     = _load_ts("status")

    while True:
        try:
            # ── Reload config on every cycle ──────────────────────────────────
            cfg = load_config()

            if not cfg.get("autonomy", {}).get("enabled", True):
                print("[HEARTBEAT] Autonomy disabled via config. Sleeping.", flush=True)
                time.sleep(300)
                continue

            mode = cfg.get("autonomy", {}).get("mode", "full")
            ivl  = cfg.get("intervals", {})

            heartbeat_sec    = ivl.get("heartbeat_seconds", 1800)
            briefing_hrs     = ivl.get("morning_briefing_hours", 6)
            opp_scan_hrs     = ivl.get("opportunity_scan_hours", 8)
            status_hrs       = ivl.get("status_update_hours", 2)

            briefing_sec     = briefing_hrs  * 3600
            opp_scan_sec     = opp_scan_hrs  * 3600
            status_sec       = status_hrs    * 3600

            now = time.time()

            # Get active session (used by all functions that write to Mission Control)
            session_id = get_active_session()

            # ── Morning briefing ───────────────────────────────────────────────
            if (cfg.get("morning_briefing", {}).get("enabled", True)
                    and mode in ("full", "briefing_only")
                    and (now - _last_briefing) >= briefing_sec):
                run_morning_briefing(session_id, cfg)
                _last_briefing = now
                _save_ts("briefing", now)

            # ── Opportunity scan ───────────────────────────────────────────────
            if (cfg.get("opportunity_scan", {}).get("enabled", True)
                    and mode == "full"
                    and (now - _last_opp_scan) >= opp_scan_sec):
                run_opportunity_scan(session_id, cfg)
                _last_opp_scan = now
                _save_ts("opp_scan", now)

            # ── Status update ──────────────────────────────────────────────────
            if (cfg.get("status_update", {}).get("enabled", True)
                    and mode != "off"
                    and (now - _last_status) >= status_sec):
                run_status_update(session_id, cfg)
                _last_status = now
                _save_ts("status", now)

            # ── Sleep until next check ─────────────────────────────────────────
            time.sleep(heartbeat_sec)

        except Exception as e:
            print(f"[HEARTBEAT] Loop error: {e}", flush=True)
            time.sleep(60)  # Short sleep on error, then retry


# ── Legacy compatibility ──────────────────────────────────────────────────────

def run_heartbeat():
    """Legacy entry point — redirects to hybrid_autonomy_loop."""
    hybrid_autonomy_loop()


if __name__ == "__main__":
    hybrid_autonomy_loop()
