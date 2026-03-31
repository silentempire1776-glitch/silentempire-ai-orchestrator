"""
=========================================================
Voice Agent — Silent Empire Elite Communication Module
Version: 1.0

Purpose:
  Handles ALL voice interactions — inbound and outbound.
  Provider-agnostic: plug in any STT/TTS/telephony provider
  by setting env vars. No code changes needed to switch.

Supported provider combinations (set via .env):
  TELEPHONY:  twilio | vonage | signalwire
  STT:        deepgram | whisper | assemblyai
  TTS:        elevenlabs | cartesia | openai | google

Task types handled:
  - "outbound_call"   : initiate a call to a number
  - "handle_inbound"  : process an incoming call webhook
  - "voice_message"   : generate TTS audio and send/store
  - "transcribe"      : transcribe audio file → text
  - "chat"            : passthrough

Architecture:
  Voice Agent sits between telephony providers and Jarvis.
  - Inbound: webhook → Voice Agent → Jarvis chat → TTS → caller
  - Outbound: Jarvis triggers → Voice Agent → call → conversation
  - TTS generation: any agent requests audio → Voice Agent returns URL

MCP tools used:
  - llm_router.run        : generate conversation responses
  - crm.upsert_contact    : log caller as contact
  - crm.create_ticket     : log call as customer service ticket
  - memory.store_result   : store call transcript
  - memory.get_agent_memory: retrieve caller history
=========================================================
"""

import json
import os
import sys
import time
import traceback
import uuid
import base64
from typing import Any, Dict, Optional, List

import requests as _http

sys.path.insert(0, "/ai-firm")

from shared.redis_bus import enqueue, dequeue_blocking
from shared.artifact import build_artifact
from shared.artifact_store import stage_already_completed, mark_stage_completed

# --------------------------------------------------
# CONSTANTS
# --------------------------------------------------

AGENT_NAME  = "voice"
QUEUE_NAME  = "queue.agent.voice"
RETRY_QUEUE = "queue.agent.voice.retry"
DEAD_QUEUE  = "queue.agent.voice.dead"
MAX_RETRIES = 3

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")

# --------------------------------------------------
# PROVIDER CONFIG (all via .env — no hardcoding)
# --------------------------------------------------

# Telephony
TELEPHONY_PROVIDER = os.getenv("TELEPHONY_PROVIDER", "twilio").lower()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
VONAGE_API_KEY     = os.getenv("VONAGE_API_KEY", "")
VONAGE_API_SECRET  = os.getenv("VONAGE_API_SECRET", "")

# STT (Speech to Text)
STT_PROVIDER   = os.getenv("STT_PROVIDER", "deepgram").lower()
DEEPGRAM_KEY   = os.getenv("DEEPGRAM_API_KEY", "")
ASSEMBLYAI_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")
WHISPER_KEY    = os.getenv("OPENAI_API_KEY", "")  # OpenAI Whisper

# TTS (Text to Speech)
TTS_PROVIDER       = os.getenv("TTS_PROVIDER", "elevenlabs").lower()
ELEVENLABS_KEY     = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE   = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
CARTESIA_KEY       = os.getenv("CARTESIA_API_KEY", "")
CARTESIA_VOICE     = os.getenv("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")
OPENAI_TTS_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_TTS_VOICE   = os.getenv("OPENAI_TTS_VOICE", "nova")  # alloy|echo|fable|onyx|nova|shimmer
GOOGLE_TTS_KEY     = os.getenv("GOOGLE_TTS_KEY", "")

# Audio storage
AUDIO_STORAGE_PATH = os.getenv("AUDIO_STORAGE_PATH", "/ai-firm/logs/audio")
os.makedirs(AUDIO_STORAGE_PATH, exist_ok=True)

# Webhook base URL (for Twilio callbacks)
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")

# --------------------------------------------------
# MCP CLIENT
# --------------------------------------------------

try:
    from mcp.shared.mcp_protocol import MCPClient
    _mcp = MCPClient()
    MCP_AVAILABLE = True
    print("[VOICE] MCP client loaded.", flush=True)
except Exception as e:
    print(f"[VOICE] MCP unavailable: {e}", flush=True)
    MCP_AVAILABLE = False
    _mcp = None


def mcp(server: str, tool: str, params: dict, fallback=None):
    if not MCP_AVAILABLE or _mcp is None:
        return fallback
    try:
        return _mcp.call_tool(server, tool, params, timeout=30)
    except Exception as e:
        print(f"[VOICE] MCP {server}.{tool} failed: {e}", flush=True)
        return fallback


# --------------------------------------------------
# SAFE NORMALIZER
# --------------------------------------------------

def _as_dict(obj: Any) -> Dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8", errors="replace")
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return parsed if isinstance(parsed, dict) else {"_value": parsed}
        except Exception:
            return {}
    try:
        return dict(obj)
    except Exception:
        return {}


# ==================================================
# STT — SPEECH TO TEXT
# ==================================================

def transcribe_audio(audio_url: str = None, audio_bytes: bytes = None) -> str:
    """
    Transcribe audio from URL or raw bytes.
    Routes to configured STT provider.
    """
    if STT_PROVIDER == "deepgram" and DEEPGRAM_KEY:
        return _transcribe_deepgram(audio_url, audio_bytes)
    elif STT_PROVIDER == "assemblyai" and ASSEMBLYAI_KEY:
        return _transcribe_assemblyai(audio_url)
    elif STT_PROVIDER == "whisper" and WHISPER_KEY:
        return _transcribe_whisper(audio_bytes)
    else:
        # Auto-detect based on available keys
        if DEEPGRAM_KEY:
            return _transcribe_deepgram(audio_url, audio_bytes)
        if WHISPER_KEY:
            return _transcribe_whisper(audio_bytes)
        return "[STT provider not configured]"


def _transcribe_deepgram(audio_url: str = None, audio_bytes: bytes = None) -> str:
    try:
        headers = {
            "Authorization": f"Token {DEEPGRAM_KEY}",
            "Content-Type": "application/json" if audio_url else "audio/*",
        }
        params = {"punctuate": "true", "model": "nova-2", "language": "en-US"}

        if audio_url:
            resp = _http.post(
                "https://api.deepgram.com/v1/listen",
                headers=headers,
                json={"url": audio_url},
                params=params,
                timeout=30
            )
        else:
            headers["Content-Type"] = "audio/wav"
            resp = _http.post(
                "https://api.deepgram.com/v1/listen",
                headers=headers,
                data=audio_bytes,
                params=params,
                timeout=30
            )

        resp.raise_for_status()
        data = resp.json()
        transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
        return transcript.strip()
    except Exception as e:
        print(f"[VOICE] Deepgram error: {e}", flush=True)
        return ""


def _transcribe_assemblyai(audio_url: str) -> str:
    try:
        # Submit
        resp = _http.post(
            "https://api.assemblyai.com/v2/transcript",
            headers={"authorization": ASSEMBLYAI_KEY},
            json={"audio_url": audio_url},
            timeout=15
        )
        resp.raise_for_status()
        transcript_id = resp.json()["id"]

        # Poll
        for _ in range(60):
            poll = _http.get(
                f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                headers={"authorization": ASSEMBLYAI_KEY},
                timeout=10
            )
            data = poll.json()
            if data["status"] == "completed":
                return data["text"]
            if data["status"] == "error":
                return ""
            time.sleep(2)
        return ""
    except Exception as e:
        print(f"[VOICE] AssemblyAI error: {e}", flush=True)
        return ""


def _transcribe_whisper(audio_bytes: bytes) -> str:
    try:
        resp = _http.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {WHISPER_KEY}"},
            files={"file": ("audio.wav", audio_bytes, "audio/wav")},
            data={"model": "whisper-1"},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json().get("text", "").strip()
    except Exception as e:
        print(f"[VOICE] Whisper error: {e}", flush=True)
        return ""


# ==================================================
# TTS — TEXT TO SPEECH
# ==================================================

def synthesize_speech(text: str, output_path: str = None) -> Optional[str]:
    """
    Convert text to speech audio.
    Routes to configured TTS provider.
    Returns path to saved audio file or None.
    """
    if not output_path:
        output_path = os.path.join(AUDIO_STORAGE_PATH, f"{uuid.uuid4()}.mp3")

    if TTS_PROVIDER == "elevenlabs" and ELEVENLABS_KEY:
        return _tts_elevenlabs(text, output_path)
    elif TTS_PROVIDER == "cartesia" and CARTESIA_KEY:
        return _tts_cartesia(text, output_path)
    elif TTS_PROVIDER == "openai" and OPENAI_TTS_KEY:
        return _tts_openai(text, output_path)
    elif TTS_PROVIDER == "google" and GOOGLE_TTS_KEY:
        return _tts_google(text, output_path)
    else:
        # Auto-detect based on available keys
        if ELEVENLABS_KEY:
            return _tts_elevenlabs(text, output_path)
        if OPENAI_TTS_KEY:
            return _tts_openai(text, output_path)
        print("[VOICE] No TTS provider configured", flush=True)
        return None


def _tts_elevenlabs(text: str, output_path: str) -> Optional[str]:
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}"
        headers = {
            "xi-api-key": ELEVENLABS_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        body = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",  # fastest, most natural
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            }
        }
        resp = _http.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(resp.content)
        print(f"[VOICE] ElevenLabs TTS → {output_path}", flush=True)
        return output_path
    except Exception as e:
        print(f"[VOICE] ElevenLabs error: {e}", flush=True)
        return None


def _tts_cartesia(text: str, output_path: str) -> Optional[str]:
    try:
        url = "https://api.cartesia.ai/tts/bytes"
        headers = {
            "X-API-Key": CARTESIA_KEY,
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }
        body = {
            "transcript": text,
            "model_id": "sonic-english",
            "voice": {"mode": "id", "id": CARTESIA_VOICE},
            "output_format": {"container": "mp3", "encoding": "mp3", "sample_rate": 44100},
        }
        resp = _http.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(resp.content)
        print(f"[VOICE] Cartesia TTS → {output_path}", flush=True)
        return output_path
    except Exception as e:
        print(f"[VOICE] Cartesia error: {e}", flush=True)
        return None


def _tts_openai(text: str, output_path: str) -> Optional[str]:
    try:
        resp = _http.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_TTS_KEY}"},
            json={
                "model": "tts-1-hd",
                "voice": OPENAI_TTS_VOICE,
                "input": text,
                "response_format": "mp3",
            },
            timeout=30
        )
        resp.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(resp.content)
        print(f"[VOICE] OpenAI TTS → {output_path}", flush=True)
        return output_path
    except Exception as e:
        print(f"[VOICE] OpenAI TTS error: {e}", flush=True)
        return None


def _tts_google(text: str, output_path: str) -> Optional[str]:
    try:
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_KEY}"
        body = {
            "input": {"text": text},
            "voice": {"languageCode": "en-US", "name": "en-US-Journey-F", "ssmlGender": "FEMALE"},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0, "pitch": 0.0},
        }
        resp = _http.post(url, json=body, timeout=20)
        resp.raise_for_status()
        audio_bytes = base64.b64decode(resp.json()["audioContent"])

        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        print(f"[VOICE] Google TTS → {output_path}", flush=True)
        return output_path
    except Exception as e:
        print(f"[VOICE] Google TTS error: {e}", flush=True)
        return None


# ==================================================
# TELEPHONY — OUTBOUND CALLS
# ==================================================

def initiate_call(to_number: str, message: str, chain_id: str = None) -> dict:
    """
    Initiate an outbound call with a spoken message.
    Routes to configured telephony provider.
    """
    if TELEPHONY_PROVIDER == "twilio" and TWILIO_ACCOUNT_SID:
        return _call_twilio(to_number, message)
    elif TELEPHONY_PROVIDER == "vonage" and VONAGE_API_KEY:
        return _call_vonage(to_number, message)
    else:
        # Generate TTS and return audio path if no telephony configured
        audio_path = synthesize_speech(message)
        return {
            "status": "tts_only",
            "message": "No telephony provider configured. Audio generated only.",
            "audio_path": audio_path,
            "to": to_number,
        }


def _call_twilio(to_number: str, message: str) -> dict:
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Build TwiML for the call
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="en-US">{message}</Say>
    <Pause length="1"/>
    <Gather input="speech" timeout="5" action="{WEBHOOK_BASE_URL}/voice/response">
        <Say voice="alice">Press any key or speak to respond.</Say>
    </Gather>
</Response>"""

        call = client.calls.create(
            twiml=twiml,
            to=to_number,
            from_=TWILIO_FROM_NUMBER,
        )

        return {
            "status": "initiated",
            "call_sid": call.sid,
            "to": to_number,
            "provider": "twilio",
        }
    except ImportError:
        return {"error": "twilio package not installed. Run: pip install twilio"}
    except Exception as e:
        return {"error": str(e), "provider": "twilio"}


def _call_vonage(to_number: str, message: str) -> dict:
    try:
        import vonage
        client = vonage.Client(key=VONAGE_API_KEY, secret=VONAGE_API_SECRET)
        voice  = vonage.Voice(client)

        response = voice.create_call({
            "to": [{"type": "phone", "number": to_number}],
            "from": {"type": "phone", "number": os.getenv("VONAGE_FROM_NUMBER", "")},
            "ncco": [{"action": "talk", "text": message, "voiceName": "Amy"}]
        })

        return {
            "status": "initiated",
            "uuid": response.get("uuid"),
            "to": to_number,
            "provider": "vonage",
        }
    except ImportError:
        return {"error": "vonage package not installed. Run: pip install vonage"}
    except Exception as e:
        return {"error": str(e), "provider": "vonage"}


# ==================================================
# CONVERSATION ENGINE
# Handles the AI conversation during a live call
# ==================================================

def generate_call_response(
    caller_message: str,
    caller_number: str,
    conversation_history: List[dict],
    context: str = ""
) -> str:
    """
    Generate an AI response during a live voice call.
    Keeps responses short and natural for voice.
    """

    # Get caller history from memory
    caller_memory = ""
    if MCP_AVAILABLE and caller_number:
        caller_memory = mcp(
            "memory", "get_agent_memory",
            {"agent": "voice", "key": f"caller:{caller_number}"},
            fallback=""
        ) or ""

    system_prompt = (
        "You are a professional AI representative for Silent Empire AI. "
        "You are on a live phone call. Keep responses SHORT — 1-3 sentences maximum. "
        "Be warm, professional, and direct. "
        "Do not use bullet points, markdown, or lists — speak naturally. "
        "If the caller wants to make a purchase, collect their information and offer to send a payment link. "
        "If they have a support issue, acknowledge it and tell them it will be resolved. "
    )

    if caller_memory:
        system_prompt += f"\nCaller history: {caller_memory}"
    if context:
        system_prompt += f"\nContext: {context}"

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-6:])  # last 3 exchanges
    messages.append({"role": "user", "content": caller_message})

    response = ""
    if MCP_AVAILABLE:
        result = mcp("llm_router", "run", {
            "model":    mcp("llm_router", "get_model_for_role", {"role": "voice"}) or "meta/llama-4-maverick-17b-128e-instruct",
            "messages": messages,
            "agent":    AGENT_NAME,
        })
        if result:
            response = result.get("content", "")

    if not response:
        # Direct fallback
        nvidia_key = os.getenv("NVIDIA_API_KEY") or os.getenv("MOONSHOT_API_KEY")
        if nvidia_key:
            try:
                resp = _http.post(
                    f"{os.getenv('NVIDIA_BASE_URL', 'https://integrate.api.nvidia.com/v1')}/chat/completions",
                    headers={"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"},
                    json={"model": "meta/llama-4-maverick-17b-128e-instruct",
                          "messages": messages, "temperature": 0.6, "max_tokens": 150},
                    timeout=10,
                )
                resp.raise_for_status()
                response = resp.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"[VOICE] LLM fallback failed: {e}", flush=True)

    return response or "I apologize, I'm having a technical issue. Please call back in a moment."


# ==================================================
# HANDLE INBOUND CALL (webhook data)
# ==================================================

def handle_inbound(payload: dict, chain_id: str = None) -> dict:
    """
    Process an incoming call webhook.
    Payload from Twilio/Vonage contains caller info + speech transcript.
    """
    caller_number  = payload.get("from") or payload.get("caller_number", "unknown")
    caller_speech  = payload.get("SpeechResult") or payload.get("transcript", "")
    call_sid       = payload.get("CallSid") or payload.get("call_id", "")
    conversation   = payload.get("conversation_history", [])

    print(f"[VOICE] Inbound from {caller_number}: {caller_speech[:80]}", flush=True)

    # Log caller to CRM
    if MCP_AVAILABLE and caller_number != "unknown":
        mcp("crm", "upsert_contact", {
            "phone": caller_number,
            "source": "inbound_call",
            "tags": ["caller"],
        })

    # Generate response
    response_text = generate_call_response(
        caller_speech,
        caller_number,
        conversation,
    )

    # Generate TTS audio
    audio_path = synthesize_speech(response_text)

    # Update conversation history in memory
    if MCP_AVAILABLE and caller_number != "unknown":
        history = conversation + [
            {"role": "user", "content": caller_speech},
            {"role": "assistant", "content": response_text},
        ]
        mcp("memory", "set_agent_memory", {
            "agent": "voice",
            "key": f"caller:{caller_number}",
            "value": json.dumps(history[-10:])  # keep last 5 exchanges
        })

    # Build Twilio TwiML response
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="en-US">{response_text}</Say>
    <Gather input="speech" timeout="5" action="{WEBHOOK_BASE_URL}/voice/response" method="POST">
        <Pause length="1"/>
    </Gather>
    <Say voice="alice">I didn't catch that. Thank you for calling Silent Empire AI.</Say>
</Response>"""

    return {
        "response_text": response_text,
        "audio_path": audio_path,
        "twiml": twiml,
        "caller": caller_number,
        "call_sid": call_sid,
    }


# ==================================================
# PROCESS TASK
# ==================================================

def process_task(raw_envelope: Any) -> None:
    envelope  = _as_dict(raw_envelope)

    if not isinstance(envelope, dict) or not envelope:
        print("[VOICE] Skipping invalid envelope", flush=True)
        return

    doctrine  = _as_dict(envelope.get("doctrine"))
    task_type = envelope.get("task_type")
    payload   = _as_dict(envelope.get("payload"))
    chain_id  = payload.get("chain_id")

    if not task_type:
        print("[VOICE] Missing task_type", flush=True)
        return

    if chain_id and stage_already_completed(chain_id, AGENT_NAME):
        print(f"[VOICE] Stage already completed: {chain_id}", flush=True)
        return

    print(f"[VOICE] Task: {task_type} | chain_id={chain_id}", flush=True)

    # ── CHAT PASSTHROUGH ────────────────────────────────────────────
    if task_type == "chat":
        msg = payload.get("message") or payload.get("product", "")
        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)
        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": "chat",
            "result": build_artifact("chat_echo", "1.0", {"text": f"[Voice Agent] {msg}"}),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── OUTBOUND CALL ───────────────────────────────────────────────
    if task_type == "outbound_call":
        to_number = payload.get("to") or payload.get("phone", "")
        message   = payload.get("message") or payload.get("script", "")

        if not to_number:
            result = {"error": "to number required"}
        elif not message:
            result = {"error": "message/script required"}
        else:
            result = initiate_call(to_number, message, chain_id)

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("outbound_call", "1.0", result),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── HANDLE INBOUND ──────────────────────────────────────────────
    if task_type == "handle_inbound":
        result = handle_inbound(payload, chain_id)

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("inbound_call", "1.0", result),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── VOICE MESSAGE (TTS only) ─────────────────────────────────────
    if task_type == "voice_message":
        text       = payload.get("text") or payload.get("message", "")
        output_path = payload.get("output_path")
        audio_path  = synthesize_speech(text, output_path)

        result = {
            "success": audio_path is not None,
            "audio_path": audio_path,
            "text": text,
            "provider": TTS_PROVIDER,
        }

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("voice_message", "1.0", result),
            "payload": payload, "doctrine": doctrine,
        })
        return

    # ── TRANSCRIBE ──────────────────────────────────────────────────
    if task_type == "transcribe":
        audio_url = payload.get("audio_url")
        transcript = transcribe_audio(audio_url=audio_url)

        result = {
            "transcript": transcript,
            "audio_url": audio_url,
            "provider": STT_PROVIDER,
        }

        if chain_id:
            mark_stage_completed(chain_id, AGENT_NAME)

        enqueue("queue.orchestrator.results", {
            "agent": AGENT_NAME, "task_type": task_type,
            "result": build_artifact("transcription", "1.0", result),
            "payload": payload, "doctrine": doctrine,
        })
        return

    print(f"[VOICE] Unknown task type: {task_type}", flush=True)


# --------------------------------------------------
# MAIN LOOP
# --------------------------------------------------

def run() -> None:
    print(f"[VOICE] Elite Voice Agent online.", flush=True)
    print(f"[VOICE] Telephony: {TELEPHONY_PROVIDER} | STT: {STT_PROVIDER} | TTS: {TTS_PROVIDER}", flush=True)

    # Log which providers are configured
    providers_ready = []
    if ELEVENLABS_KEY:   providers_ready.append("ElevenLabs TTS")
    if DEEPGRAM_KEY:     providers_ready.append("Deepgram STT")
    if ASSEMBLYAI_KEY:   providers_ready.append("AssemblyAI STT")
    if TWILIO_ACCOUNT_SID: providers_ready.append("Twilio")
    if CARTESIA_KEY:     providers_ready.append("Cartesia TTS")
    if OPENAI_TTS_KEY:   providers_ready.append("OpenAI TTS/STT")

    if providers_ready:
        print(f"[VOICE] Providers configured: {', '.join(providers_ready)}", flush=True)
    else:
        print("[VOICE] WARNING: No voice providers configured. Add API keys to .env", flush=True)

    while True:
        try:
            raw      = dequeue_blocking(QUEUE_NAME)
            envelope = _as_dict(raw)
            retry    = envelope.get("retry_count", 0)

            try:
                process_task(envelope)

            except Exception as error:
                retry += 1
                envelope["retry_count"] = retry
                tb = traceback.format_exc()
                print(f"[VOICE ERROR] retry={retry} | {error}", flush=True)
                print(tb, flush=True)

                if retry < MAX_RETRIES:
                    enqueue(RETRY_QUEUE, envelope)
                else:
                    enqueue(DEAD_QUEUE, envelope)
                    enqueue("queue.orchestrator.results", {
                        "agent": AGENT_NAME,
                        "task_type": envelope.get("task_type"),
                        "result": build_artifact("error", "1.0", {
                            "error": str(error), "retry_count": retry
                        }),
                        "payload":  envelope.get("payload"),
                        "doctrine": envelope.get("doctrine"),
                        "status":   "failed",
                    })

        except Exception as queue_error:
            print(f"[VOICE QUEUE ERROR] {queue_error}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    run()
