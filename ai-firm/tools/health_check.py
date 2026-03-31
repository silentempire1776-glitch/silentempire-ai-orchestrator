#!/usr/bin/env python3
"""
Silent Empire agent container health check.

Checks every AI-firm container is in the 'running' state and logs any that
are down.  Exits with code 1 if one or more containers are not running.

Usage:
    python health_check.py [--log-file PATH]

Environment:
    HEALTH_LOG_FILE  Override the default log file path (optional).
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Container registry — every service defined in ai-firm/docker-compose.yml
# ---------------------------------------------------------------------------
CONTAINERS = [
    # Orchestration
    "jarvis-orchestrator",
    "jarvis-timeout-monitor",
    # Agents
    "research-agent",
    "revenue-agent",
    "sales-agent",
    "growth-agent",
    "product-agent",
    "legal-agent",
    "systems-agent",
    "code-agent",
    "voice-agent",
    # Tools
    "tool-executor",
    # MCP servers
    "mcp-memory",
    "mcp-llm-router",
    "mcp-filesystem",
    "mcp-crm",
    "mcp-infra",
]

DEFAULT_LOG_FILE = os.environ.get(
    "HEALTH_LOG_FILE",
    "/srv/silentempire/ai-firm/logs/health_check.log",
)


def setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("health_check")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    # Use UTC in timestamps
    logging.Formatter.converter = lambda *_: datetime.now(timezone.utc).timetuple()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Cannot open log file %s: %s — logging to stdout only", log_file, exc)

    return logger


def inspect_container(name: str) -> dict | None:
    """Return the docker inspect JSON dict for *name*, or None if not found."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .State}}", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout.strip())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def check_containers(logger: logging.Logger) -> list[str]:
    """
    Check each container and log its status.

    Returns a list of container names that are NOT running.
    """
    down: list[str] = []
    logger.info("=== Silent Empire agent health check ===")

    for name in CONTAINERS:
        state = inspect_container(name)

        if state is None:
            logger.error("DOWN  %-30s  container not found / docker inspect failed", name)
            down.append(name)
            continue

        status = state.get("Status", "unknown")
        running = state.get("Running", False)

        if running and status == "running":
            started_at = state.get("StartedAt", "")
            logger.info("UP    %-30s  status=%s  started=%s", name, status, started_at)
        else:
            exit_code = state.get("ExitCode", "?")
            error = state.get("Error", "")
            detail = f"status={status}  exit_code={exit_code}"
            if error:
                detail += f"  error={error!r}"
            logger.error("DOWN  %-30s  %s", name, detail)
            down.append(name)

    return down


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Silent Empire agent containers.")
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_FILE,
        help=f"Path to the log file (default: {DEFAULT_LOG_FILE})",
    )
    args = parser.parse_args()

    logger = setup_logging(args.log_file)
    down = check_containers(logger)

    total = len(CONTAINERS)
    up_count = total - len(down)

    logger.info("--- Summary: %d/%d containers running ---", up_count, total)

    if down:
        logger.error("Containers NOT running (%d): %s", len(down), ", ".join(down))
        return 1

    logger.info("All %d containers are running.", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
