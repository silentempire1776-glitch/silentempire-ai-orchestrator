"""
=========================================================
Voice Routes — Silent Empire FastAPI Extensions
Handles Twilio/Vonage webhooks and voice task triggers.

Save as: /srv/silentempire/app/services/api/voice_routes.py
Then add to main.py:
  from voice_routes import router as voice_router
  app.include_router(voice_router)

Endpoints:
  POST /voice/inbound          ← Twilio/Vonage webhook (new call)
  POST /voice/response         ← Twilio/Vonage webhook (caller spoke)
  POST /voice/outbound         ← Trigger outbound call from Mission Control
  POST /voice/tts              ← Generate TTS audio
  POST /voice/transcribe       ← Transcribe audio URL
  GET  /voice/audio/{filename} ← Serve generated audio files
=========================================================
"""

import os
import uuid
import json
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()

AUDIO_PATH = os.getenv("AUDIO_STORAGE_PATH", "/ai-firm/logs/audio")


def _enqueue_voice_task(task_type: str, payload: dict) -> str:
    from shared.redis_bus import enqueue
    chain_id = str(uuid.uuid4())
    enqueue("queue.agent.voice", {
        "task_type": task_type,
        "payload": {**payload, "chain_id": chain_id},
        "doctrine": {},
    })
    return chain_id


# --------------------------------------------------
# TWILIO INBOUND WEBHOOK
# Called by Twilio when someone calls your number
# --------------------------------------------------

@router.post("/voice/inbound")
async def voice_inbound(request: Request):
    """
    Twilio calls this when someone dials your Twilio number.
    Returns TwiML to gather speech.
    """
    form = await request.form()
    caller = form.get("From", "unknown")
    call_sid = form.get("CallSid", "")

    # Return TwiML to greet and gather speech
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" timeout="5" action="/voice/response" method="POST" speechTimeout="auto">
        <Say voice="alice" language="en-US">
            Thank you for calling Silent Empire AI. How can I help you today?
        </Say>
    </Gather>
    <Say voice="alice">I didn't catch that. Please call back and try again.</Say>
</Response>"""

    return Response(content=twiml, media_type="text/xml")


# --------------------------------------------------
# TWILIO RESPONSE WEBHOOK
# Called by Twilio when caller speaks
# --------------------------------------------------

@router.post("/voice/response")
async def voice_response(request: Request):
    """
    Twilio calls this after gathering caller speech.
    Routes to voice agent for AI response generation.
    """
    form = await request.form()

    payload = {
        "from": form.get("From", "unknown"),
        "CallSid": form.get("CallSid", ""),
        "SpeechResult": form.get("SpeechResult", ""),
        "Confidence": form.get("Confidence", ""),
        "conversation_history": [],
    }

    # Dispatch to voice agent (async — don't wait)
    chain_id = _enqueue_voice_task("handle_inbound", payload)

    # Return immediate TwiML while agent processes
    # In production, use Twilio's <Redirect> to poll for the response
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Pause length="2"/>
    <Gather input="speech" timeout="5" action="/voice/response" method="POST">
        <Say voice="alice">One moment please.</Say>
    </Gather>
</Response>"""

    return Response(content=twiml, media_type="text/xml")


# --------------------------------------------------
# TRIGGER OUTBOUND CALL (from Mission Control)
# --------------------------------------------------

class OutboundCallRequest(BaseModel):
    to: str
    message: str
    contact_id: Optional[str] = None


@router.post("/voice/outbound")
def trigger_outbound_call(req: OutboundCallRequest):
    chain_id = _enqueue_voice_task("outbound_call", {
        "to": req.to,
        "message": req.message,
        "contact_id": req.contact_id or "",
    })
    return {"chain_id": chain_id, "status": "queued", "to": req.to}


# --------------------------------------------------
# TTS GENERATION (from any agent or Mission Control)
# --------------------------------------------------

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None


@router.post("/voice/tts")
def generate_tts(req: TTSRequest):
    chain_id = _enqueue_voice_task("voice_message", {
        "text": req.text,
    })
    return {"chain_id": chain_id, "status": "queued"}


# --------------------------------------------------
# TRANSCRIPTION
# --------------------------------------------------

class TranscribeRequest(BaseModel):
    audio_url: str


@router.post("/voice/transcribe")
def transcribe_audio(req: TranscribeRequest):
    chain_id = _enqueue_voice_task("transcribe", {
        "audio_url": req.audio_url,
    })
    return {"chain_id": chain_id, "status": "queued"}


# --------------------------------------------------
# SERVE AUDIO FILES
# --------------------------------------------------

@router.get("/voice/audio/{filename}")
def serve_audio(filename: str):
    # Security: only serve from audio directory, no path traversal
    safe_name = os.path.basename(filename)
    path = os.path.join(AUDIO_PATH, safe_name)
    if not os.path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/mpeg")
