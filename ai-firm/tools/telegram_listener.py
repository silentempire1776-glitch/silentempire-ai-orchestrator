#!/usr/bin/env python3
"""
Telegram bot listener for Silent Empire AI.

Polls Telegram for incoming messages via long polling and forwards them
to Jarvis via the chat API at http://api:8000/chat.

Environment variables required:
  TELEGRAM_TOKEN    — Bot token from BotFather
  TELEGRAM_CHAT_ID  — Allowed chat ID (messages from other chats are ignored)

Optional:
  JARVIS_API_URL    — Override chat API base URL (default: http://api:8000)
  POLL_TIMEOUT      — Long-poll timeout in seconds (default: 30)
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("telegram_listener")

# ── Configuration ──────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
JARVIS_API_URL = (os.environ.get("JARVIS_API_URL") or "http://api:8000").rstrip("/")
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "30"))

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Back-off limits for transient errors
MAX_BACKOFF = 60
INITIAL_BACKOFF = 2


# ── Telegram helpers ───────────────────────────────────────────────────────────


def _post(url: str, payload: dict, timeout: int = 35) -> dict:
    """HTTP POST, returns parsed JSON response body."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: int = 35) -> dict:
    """HTTP GET, returns parsed JSON response body."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_updates(offset: int | None, timeout: int = POLL_TIMEOUT) -> list[dict]:
    """Long-poll Telegram for new updates. Returns list of update objects."""
    params = f"?timeout={timeout}"
    if offset is not None:
        params += f"&offset={offset}"
    url = f"{TELEGRAM_API}/getUpdates{params}"
    try:
        resp = _get(url, timeout=timeout + 5)
        if not resp.get("ok"):
            log.warning("getUpdates returned ok=false: %s", resp)
            return []
        return resp.get("result", [])
    except urllib.error.HTTPError as exc:
        log.error("Telegram HTTP %s: %s", exc.code, exc.read().decode())
        return []
    except Exception as exc:
        raise RuntimeError(f"getUpdates failed: {exc}") from exc


def send_reply(chat_id: str | int, text: str) -> None:
    """Send a text message back to a Telegram chat."""
    url = f"{TELEGRAM_API}/sendMessage"
    try:
        resp = _post(url, {"chat_id": chat_id, "text": text}, timeout=15)
        if not resp.get("ok"):
            log.warning("sendMessage returned ok=false: %s", resp)
    except Exception as exc:
        log.error("Failed to send Telegram reply: %s", exc)


# ── Jarvis forwarding ──────────────────────────────────────────────────────────


def get_active_session() -> str:
    """
    Fetch the most recently active Mission Control session ID.
    Falls back to telegram:{chat_id} if API unreachable.
    """
    try:
        req = urllib.request.Request(
            f"{JARVIS_API_URL}/sessions",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            sessions = json.loads(resp.read().decode())
            if sessions and sessions[0].get("id"):
                return sessions[0]["id"]
    except Exception as exc:
        log.warning("Could not fetch active session: %s", exc)
    return ""


def post_message_to_session(session_id: str, role: str, text: str) -> None:
    """
    Append a message to the Mission Control session so it appears in the UI.
    role: 'user' for incoming Telegram messages
    """
    try:
        # Get current messages
        req = urllib.request.Request(
            f"{JARVIS_API_URL}/sessions/{session_id}",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        messages = data.get("messages", [])
        if isinstance(messages, str):
            messages = json.loads(messages)
        # Append new message
        import uuid as _uuid
        messages.append({
            "id": str(_uuid.uuid4())[:8],
            "role": role,
            "content": f"[Telegram] {text}",
            "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
        })
        # Write back
        payload = json.dumps({"messages": messages}).encode()
        put_req = urllib.request.Request(
            f"{JARVIS_API_URL}/sessions/{session_id}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(put_req, timeout=5) as resp:
            pass
        log.info("Message written to session %s", session_id)
    except Exception as exc:
        log.warning("Could not write to session: %s", exc)


def forward_to_jarvis(message: str, session_id: str | None = None, telegram_chat_id: str | None = None) -> str:
    """
    POST to /chat and return the chain_id.
    Also tries /chat/client if the simple endpoint returns no useful reply.
    """
    url = f"{JARVIS_API_URL}/chat"
    payload: dict = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    if telegram_chat_id:
        payload["telegram_chat_id"] = telegram_chat_id

    try:
        resp = _post(url, payload, timeout=60)
        chain_id = resp.get("chain_id", "")
        mode = resp.get("mode", "")
        log.info("Jarvis accepted message — chain_id=%s mode=%s", chain_id, mode)
        return chain_id
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"Jarvis API HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Jarvis forward failed: {exc}") from exc


# ── Message processing ─────────────────────────────────────────────────────────


def process_update(update: dict) -> None:
    """Handle a single Telegram update object."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        log.debug("Skipping non-message update %s", update.get("update_id"))
        return

    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    from_user = message.get("from", {})
    username = from_user.get("username") or from_user.get("first_name") or "unknown"
    text = (message.get("text") or "").strip()

    if not text:
        log.debug("Skipping update with no text from chat %s", chat_id)
        return

    # Enforce allowed chat ID
    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
        log.warning(
            "Message from unauthorized chat %s (user=%s) — ignored", chat_id, username
        )
        return

    log.info("Received from %s (chat=%s): %s", username, chat_id, text[:120])

    # Forward to Jarvis
    try:
        # Use active Mission Control session so messages appear in UI
        active_session = get_active_session() or f"telegram:{chat_id}"
        log.info("Using session: %s", active_session)
        # Write incoming message to Mission Control session
        if active_session and not active_session.startswith("telegram:"):
            post_message_to_session(active_session, "user", text)
        chain_id = forward_to_jarvis(text, session_id=active_session, telegram_chat_id=chat_id)
        log.info("Forwarded to Jarvis — chain_id=%s session=%s", chain_id, active_session)
    except RuntimeError as exc:
        log.error("Jarvis forward error: %s", exc)
        send_reply(chat_id, f"Error forwarding to Jarvis: {exc}")


# ── Main polling loop ──────────────────────────────────────────────────────────


def validate_env() -> None:
    """Raise on missing required environment variables."""
    errors = []
    if not TELEGRAM_TOKEN:
        errors.append("TELEGRAM_TOKEN is not set")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID is not set")
    if errors:
        for err in errors:
            log.error(err)
        sys.exit(1)


def run() -> None:
    validate_env()

    log.info(
        "Telegram listener starting — chat_id=%s jarvis=%s poll_timeout=%ds",
        TELEGRAM_CHAT_ID,
        JARVIS_API_URL,
        POLL_TIMEOUT,
    )

    offset: int | None = None
    backoff = INITIAL_BACKOFF

    while True:
        try:
            updates = get_updates(offset, timeout=POLL_TIMEOUT)
            backoff = INITIAL_BACKOFF  # reset on success

            for update in updates:
                update_id = update.get("update_id")
                try:
                    process_update(update)
                except Exception as exc:
                    log.error("Error processing update %s: %s", update_id, exc)
                # Advance offset past this update regardless of success
                if update_id is not None:
                    offset = update_id + 1

        except RuntimeError as exc:
            log.error("Polling error: %s — retrying in %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
        except KeyboardInterrupt:
            log.info("Shutdown requested — exiting.")
            sys.exit(0)
        except Exception as exc:
            log.error("Unexpected error: %s — retrying in %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)


if __name__ == "__main__":
    run()
