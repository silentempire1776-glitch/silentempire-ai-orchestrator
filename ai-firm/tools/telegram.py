#!/usr/bin/env python3
"""
Telegram notification tool for Silent Empire AI.
Usage: python3 telegram.py "Your message here"
"""

import os
import sys
import json
import urllib.request
import urllib.error


def send_message(message: str) -> dict:
    """Send a message to the configured Telegram chat. Returns parsed API response."""
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

    if not token:
        raise EnvironmentError("TELEGRAM_TOKEN is not set or empty")
    if not chat_id:
        raise EnvironmentError("TELEGRAM_CHAT_ID is not set or empty")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"Telegram API error {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error contacting Telegram: {e.reason}") from e


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 telegram.py \"Your message here\"")
        sys.exit(1)

    message = " ".join(sys.argv[1:])

    try:
        response = send_message(message)
        if response.get("ok"):
            msg_id = response["result"]["message_id"]
            print(f"SUCCESS: Message sent (id={msg_id})")
        else:
            print(f"FAILURE: Telegram returned ok=false — {response}")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
