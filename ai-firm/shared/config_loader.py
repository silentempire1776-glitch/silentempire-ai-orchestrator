#!/usr/bin/env python3
"""
config_loader.py — Business config loader for white-label architecture.
Reads business.json + doctrine_template.md and renders the doctrine string.
Reads agents.json for per-agent role/deliverable specs.

Usage:
    from config_loader import get_doctrine, get_agent_config
    doctrine = get_doctrine()
    agent_cfg = get_agent_config("research")
"""

import json
from pathlib import Path

_CONFIG_DIR = Path("/ai-firm/config")
_BUSINESS_PATH = _CONFIG_DIR / "business.json"
_AGENTS_PATH = _CONFIG_DIR / "agents.json"
_TEMPLATE_PATH = _CONFIG_DIR / "doctrine_template.md"

_business_cache = None
_agents_cache = None
_doctrine_cache = None


def _load_business() -> dict:
    global _business_cache
    if _business_cache is None:
        _business_cache = json.loads(_BUSINESS_PATH.read_text())
    return _business_cache


def _load_agents() -> dict:
    global _agents_cache
    if _agents_cache is None:
        _agents_cache = json.loads(_AGENTS_PATH.read_text())
    return _agents_cache


def get_doctrine() -> str:
    """Render doctrine string from template + business.json. Cached after first call."""
    global _doctrine_cache
    if _doctrine_cache is not None:
        return _doctrine_cache

    b = _load_business()
    template = _TEMPLATE_PATH.read_text()

    # Build competitive advantages bullet list
    advantages = "\n".join(f"- {a}" for a in b["competitive_advantages"])

    rendered = (
        template
        .replace("{{COMPANY_NAME}}", b["company"]["name"])
        .replace("{{FOUNDER_NAME}}", b["company"]["founder"])
        .replace("{{MISSION}}", b["company"]["mission"])
        .replace("{{PRODUCT_NAME}}", b["product"]["name"])
        .replace("{{PRODUCT_DESCRIPTION}}", b["product"]["description"])
        .replace("{{PRODUCT_PURPOSE}}", b["product"]["purpose"])
        .replace("{{PRODUCT_DELIVERY}}", b["product"]["delivery"])
        .replace("{{PRODUCT_PRICE_RANGE}}", b["product"]["price_range"])
        .replace("{{PRIMARY_DEMOGRAPHIC}}", b["market"]["primary"]["demographic"])
        .replace("{{PRIMARY_PAIN}}", b["market"]["primary"]["pain"])
        .replace("{{PRIMARY_DESIRE}}", b["market"]["primary"]["desire"])
        .replace("{{PRIMARY_SOPHISTICATION}}", b["market"]["primary"]["sophistication"])
        .replace("{{SECONDARY_DEMOGRAPHIC}}", b["market"]["secondary"]["demographic"])
        .replace("{{SECONDARY_PAIN}}", b["market"]["secondary"]["pain"])
        .replace("{{SECONDARY_DESIRE}}", b["market"]["secondary"]["desire"])
        .replace("{{COMPETITIVE_ADVANTAGES}}", advantages)
        .replace("{{BRAND_POSITIONING}}", b["brand"]["positioning"])
        .replace("{{BRAND_TONE}}", b["brand"]["tone"])
        .replace("{{DEFAULT_ASSUMPTION}}", b["brand"]["default_assumption"])
    )

    _doctrine_cache = rendered
    return rendered


def get_agent_config(agent_name: str) -> dict:
    """Return config dict for a given agent name. Returns empty dict if not found."""
    agents = _load_agents()
    return agents.get(agent_name, {})


def get_company_name() -> str:
    return _load_business()["company"]["name"]


def get_product_name() -> str:
    return _load_business()["product"]["name"]


def invalidate_cache():
    """Force reload on next call — use after editing config files."""
    global _business_cache, _agents_cache, _doctrine_cache
    _business_cache = None
    _agents_cache = None
    _doctrine_cache = None
