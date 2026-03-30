#!/usr/bin/env python3
"""
Claude Code tool for Jarvis — calls claude-bridge on host.
Usage:
  python3 /ai-firm/tools/claude_code.py "instruction" [--dir /path] [--timeout 120]
"""
import sys
import argparse
import json

try:
    import requests
except ImportError:
    print("ERROR: requests not available")
    sys.exit(1)

BRIDGE_URL = "http://172.18.0.1:9999"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", help="Instruction for Claude Code")
    parser.add_argument("--dir", default="/tmp", help="Working directory")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    try:
        # Health check
        h = requests.get(f"{BRIDGE_URL}/health", timeout=5)
        if not h.ok:
            print("ERROR: Claude Code bridge not responding. Is claude-bridge running on host?")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: Cannot reach Claude Code bridge at {BRIDGE_URL}: {e}")
        print("Run on host: python3 /opt/claude-bridge/server.py &")
        sys.exit(1)

    try:
        r = requests.post(
            f"{BRIDGE_URL}/run",
            json={"prompt": args.prompt, "work_dir": args.dir, "timeout": args.timeout},
            timeout=args.timeout + 10
        )
        data = r.json()
        if data.get("success"):
            print(data["output"])
        else:
            print(f"ERROR: {data.get('output', 'Unknown error')}")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
