"""
=========================================================
MCP API Extensions — Silent Empire
New FastAPI routes that expose MCP capabilities to clients.

Add these to /srv/silentempire/app/services/api/main.py
by appending at the bottom or importing as a router.

New endpoints:
  POST /mcp/call                  → raw MCP tool call from Mission Control
  GET  /crm/contacts              → list contacts
  POST /crm/contacts              → create/update contact
  GET  /crm/pipeline              → deals pipeline
  GET  /crm/tickets               → open tickets
  POST /crm/tickets               → create ticket
  GET  /client/{client_id}/context → client portal AI context
  PUT  /client/{client_id}/context → update client AI context
  POST /chat/client               → client-side chat with guardrails
  GET  /mcp/health                → MCP server health check
=========================================================
"""

import sys
import json
import uuid
import os

# These imports assume this file is included in the api container
# which has access to /ai-firm via bind mount
sys.path.insert(0, "/ai-firm")

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

try:
    from mcp.shared.mcp_protocol import MCPClient
    _mcp = MCPClient()
    MCP_AVAILABLE = True
except Exception as e:
    print(f"[API] MCP client not available: {e}")
    MCP_AVAILABLE = False
    _mcp = None


router = APIRouter()


def mcp_call(server: str, tool: str, params: dict):
    if not MCP_AVAILABLE or _mcp is None:
        raise HTTPException(status_code=503, detail="MCP layer not available")
    try:
        return _mcp.call_tool(server, tool, params, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MCP error: {str(e)}")


# --------------------------------------------------
# RAW MCP CALL (Mission Control power tool)
# Allows Mission Control to call any MCP tool directly
# --------------------------------------------------

class MCPCallRequest(BaseModel):
    server: str
    tool: str
    params: dict = {}


@router.post("/mcp/call")
def raw_mcp_call(req: MCPCallRequest):
    result = mcp_call(req.server, req.tool, req.params)
    return {"result": result}


# --------------------------------------------------
# MCP HEALTH
# --------------------------------------------------

@router.get("/mcp/health")
def mcp_health():
    if not MCP_AVAILABLE:
        return {"status": "unavailable", "servers": {}}

    servers = ["memory", "llm_router", "filesystem", "crm", "infra"]
    health = {}

    for server in servers:
        try:
            # Each server has its queue — check if it has any pending items
            import redis as _redis
            import os as _os
            r = _redis.from_url(_os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"), decode_responses=True)
            # We can't truly ping without a tool, but we check if the queue exists
            q = f"queue.mcp.{server}"
            # A healthy server drains its queue — if huge backlog, it's stuck
            qlen = r.llen(q)
            health[server] = {"status": "ok" if qlen < 100 else "backlogged", "queue_depth": qlen}
        except Exception as e:
            health[server] = {"status": "error", "error": str(e)}

    return {"status": "ok", "servers": health, "mcp_available": MCP_AVAILABLE}


# --------------------------------------------------
# CRM ENDPOINTS
# --------------------------------------------------

@router.get("/crm/contacts")
def list_contacts(status: str = "", tag: str = "", limit: int = 50):
    return mcp_call("crm", "list_contacts", {"status": status, "tag": tag, "limit": limit})


@router.post("/crm/contacts")
async def upsert_contact(request: Request):
    body = await request.json()
    return mcp_call("crm", "upsert_contact", body)


@router.get("/crm/pipeline")
def get_pipeline():
    return {"deals": mcp_call("crm", "get_pipeline", {})}


@router.get("/crm/tickets")
def list_tickets(status: str = "open"):
    return {"tickets": mcp_call("crm", "list_tickets", {"status": status})}


@router.post("/crm/tickets")
async def create_ticket(request: Request):
    body = await request.json()
    return mcp_call("crm", "create_ticket", body)


@router.put("/crm/tickets/{ticket_id}")
async def update_ticket(ticket_id: str, request: Request):
    body = await request.json()
    body["ticket_id"] = ticket_id
    return mcp_call("crm", "update_ticket", body)


# --------------------------------------------------
# CLIENT PORTAL CONTEXT
# --------------------------------------------------

@router.get("/client/{client_id}/context")
def get_client_context(client_id: str):
    return mcp_call("crm", "get_client_context", {"client_id": client_id})


@router.put("/client/{client_id}/context")
async def set_client_context(client_id: str, request: Request):
    body = await request.json()
    body["client_id"] = client_id
    return mcp_call("crm", "set_client_context", body)


# --------------------------------------------------
# CLIENT-SIDE CHAT
# Different from /chat — uses client context and guardrails
# Powers the client portal AI chat with scoped context
# --------------------------------------------------

class ClientChatRequest(BaseModel):
    message: str
    client_id: str
    session_id: Optional[str] = None


@router.post("/chat/client")
def client_chat(req: ClientChatRequest):
    from shared.redis_bus import enqueue as _enqueue

    # Get client's AI context (guardrails + persona)
    client_ctx = {}
    if MCP_AVAILABLE:
        try:
            client_ctx = _mcp.call_tool("crm", "get_client_context", {"client_id": req.client_id}, timeout=10)
        except Exception:
            pass

    chain_id = str(uuid.uuid4())
    system_prompt = client_ctx.get("system_prompt") or (
        "You are a helpful AI assistant for this client. "
        "Answer their questions professionally and helpfully. "
        "Do not discuss internal operations, pricing structures, or other clients."
    )

    # Build a scoped jarvis_chat that uses the client's system prompt
    envelope = {
        "chain_id": chain_id,
        "task_type": "jarvis_chat",
        "target": f"client:{req.client_id}",
        "product": req.message,
        "payload": {
            "message": req.message,
            "chain_id": chain_id,
            "system_prompt_override": system_prompt,
            "client_id": req.client_id,
            "session_id": req.session_id,
        }
    }

    _enqueue("queue.orchestrator", envelope)

    return {
        "chain_id": chain_id,
        "mode": "client_chat",
        "client_id": req.client_id,
    }


# --------------------------------------------------
# PAYMENT INTENT (for chat-based sales)
# --------------------------------------------------

class PaymentIntentRequest(BaseModel):
    amount_cents: int
    contact_id: str
    description: str = "Silent Empire Service"


@router.post("/payments/intent")
def create_payment_intent(req: PaymentIntentRequest):
    return mcp_call("crm", "create_payment_intent", {
        "amount_cents": req.amount_cents,
        "contact_id": req.contact_id,
        "description": req.description,
    })


@router.post("/payments/record")
async def record_payment(request: Request):
    body = await request.json()
    return mcp_call("crm", "record_payment", body)


# --------------------------------------------------
# USAGE DASHBOARD (for Mission Control)
# --------------------------------------------------

@router.get("/metrics/llm/mcp")
def get_llm_usage():
    return mcp_call("llm_router", "get_usage_today", {})


@router.get("/metrics/models")
def list_models():
    return {"models": mcp_call("llm_router", "list_models", {})}


# --------------------------------------------------
# HOW TO REGISTER IN main.py
# --------------------------------------------------
# Add these two lines to the bottom of
# /srv/silentempire/app/services/api/main.py:
#
#   from mcp_routes import router as mcp_router
#   app.include_router(mcp_router)
#
# Then rebuild the api container:
#   cd /srv/silentempire/app && docker compose up -d --build api
