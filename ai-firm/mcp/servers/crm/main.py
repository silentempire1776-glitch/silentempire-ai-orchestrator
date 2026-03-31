"""
=========================================================
MCP CRM Server — Silent Empire
Handles the full commercial layer:
  - Contacts / leads / clients
  - Deals and pipeline
  - Payment processing (Stripe)
  - Customer service tickets
  - Chat session ownership (which client, which AI context)
  - Client portal access control

Tools:
  upsert_contact(email, name, phone, source, tags) → {id, status}
  get_contact(email)                               → dict
  list_contacts(status?, tag?, limit?)             → [dict]
  create_deal(contact_id, product, amount, stage)  → {id}
  update_deal(deal_id, stage, notes)               → {status}
  get_pipeline()                                   → [{deal}]
  create_ticket(contact_id, subject, body, priority) → {id}
  update_ticket(ticket_id, status, response)       → {status}
  list_tickets(status?)                            → [dict]
  create_payment_intent(amount_cents, contact_id, desc) → {client_secret, id}
  record_payment(contact_id, amount, product, ref) → {status}
  get_client_context(client_id)                    → {guardrails, persona, history_summary}
  set_client_context(client_id, context)           → {status}
=========================================================
"""

import os
import sys
import json
import uuid
import psycopg2
from datetime import datetime
from typing import Any, Optional

sys.path.insert(0, "/ai-firm")

from mcp.shared.mcp_protocol import MCPServer

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")
STRIPE_KEY   = os.getenv("STRIPE_SECRET_KEY", "")

# --------------------------------------------------
# DB HELPERS
# --------------------------------------------------

def _pg():
    return psycopg2.connect(DATABASE_URL)


def _init_crm_tables():
    conn = _pg()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crm_contacts (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            email TEXT UNIQUE,
            name TEXT,
            phone TEXT,
            source TEXT,
            status TEXT DEFAULT 'lead',
            tags JSONB DEFAULT '[]',
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crm_deals (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            contact_id TEXT REFERENCES crm_contacts(id),
            product TEXT,
            amount_cents INTEGER DEFAULT 0,
            stage TEXT DEFAULT 'prospecting',
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crm_tickets (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            contact_id TEXT REFERENCES crm_contacts(id),
            subject TEXT,
            body TEXT,
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'open',
            response TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crm_payments (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            contact_id TEXT REFERENCES crm_contacts(id),
            amount_cents INTEGER,
            product TEXT,
            reference TEXT,
            status TEXT DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Client portal context (per-client AI guardrails + persona)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS client_contexts (
            client_id TEXT PRIMARY KEY,
            contact_id TEXT,
            guardrails JSONB DEFAULT '{}',
            persona TEXT,
            system_prompt TEXT,
            history_summary TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("[MCP:crm] Tables initialized", flush=True)


# --------------------------------------------------
# TOOL IMPLEMENTATIONS
# --------------------------------------------------

def tool_upsert_contact(params: dict) -> dict:
    email  = params.get("email", "").lower().strip()
    name   = params.get("name", "")
    phone  = params.get("phone", "")
    source = params.get("source", "unknown")
    tags   = params.get("tags", [])

    if not email:
        raise ValueError("email required")

    conn = _pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO crm_contacts (email, name, phone, source, tags, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (email)
            DO UPDATE SET
                name       = COALESCE(NULLIF(EXCLUDED.name, ''), crm_contacts.name),
                phone      = COALESCE(NULLIF(EXCLUDED.phone, ''), crm_contacts.phone),
                source     = COALESCE(NULLIF(EXCLUDED.source, ''), crm_contacts.source),
                updated_at = NOW()
            RETURNING id, status
        """, (email, name, phone, source, json.dumps(tags)))

        row = cur.fetchone()
        conn.commit()
        return {"id": row[0], "status": row[1], "email": email}
    finally:
        cur.close()
        conn.close()


def tool_get_contact(params: dict) -> dict:
    email = params.get("email", "").lower().strip()
    cid   = params.get("id", "")

    conn = _pg()
    cur = conn.cursor()

    try:
        if email:
            cur.execute("SELECT * FROM crm_contacts WHERE email = %s", (email,))
        elif cid:
            cur.execute("SELECT * FROM crm_contacts WHERE id = %s", (cid,))
        else:
            raise ValueError("email or id required")

        row = cur.fetchone()
        if not row:
            return {}

        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    finally:
        cur.close()
        conn.close()


def tool_list_contacts(params: dict) -> list:
    status = params.get("status", "")
    tag    = params.get("tag", "")
    limit  = int(params.get("limit", 50))

    conn = _pg()
    cur = conn.cursor()

    try:
        query = "SELECT id, email, name, phone, status, source, tags, created_at FROM crm_contacts"
        args = []
        conditions = []

        if status:
            conditions.append("status = %s")
            args.append(status)
        if tag:
            conditions.append("tags @> %s")
            args.append(json.dumps([tag]))

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += f" ORDER BY created_at DESC LIMIT {limit}"

        cur.execute(query, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def tool_create_deal(params: dict) -> dict:
    contact_id = params.get("contact_id")
    product    = params.get("product", "")
    amount     = int(params.get("amount_cents", 0))
    stage      = params.get("stage", "prospecting")

    if not contact_id:
        raise ValueError("contact_id required")

    conn = _pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO crm_deals (contact_id, product, amount_cents, stage)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (contact_id, product, amount, stage))
        deal_id = cur.fetchone()[0]
        conn.commit()
        return {"id": deal_id, "stage": stage}
    finally:
        cur.close()
        conn.close()


def tool_update_deal(params: dict) -> dict:
    deal_id = params.get("deal_id")
    stage   = params.get("stage")
    notes   = params.get("notes")

    if not deal_id:
        raise ValueError("deal_id required")

    conn = _pg()
    cur = conn.cursor()

    try:
        updates = ["updated_at = NOW()"]
        args = []
        if stage:
            updates.append("stage = %s")
            args.append(stage)
        if notes:
            updates.append("notes = %s")
            args.append(notes)

        args.append(deal_id)
        cur.execute(f"UPDATE crm_deals SET {', '.join(updates)} WHERE id = %s", args)
        conn.commit()
        return {"status": "updated", "deal_id": deal_id}
    finally:
        cur.close()
        conn.close()


def tool_get_pipeline(params: dict) -> list:
    conn = _pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT d.id, d.product, d.amount_cents, d.stage, d.notes,
                   c.email, c.name, d.created_at
            FROM crm_deals d
            JOIN crm_contacts c ON c.id = d.contact_id
            ORDER BY d.created_at DESC
            LIMIT 100
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def tool_create_ticket(params: dict) -> dict:
    contact_id = params.get("contact_id")
    subject    = params.get("subject", "")
    body       = params.get("body", "")
    priority   = params.get("priority", "normal")

    conn = _pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO crm_tickets (contact_id, subject, body, priority)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (contact_id, subject, body, priority))
        ticket_id = cur.fetchone()[0]
        conn.commit()
        return {"id": ticket_id, "status": "open"}
    finally:
        cur.close()
        conn.close()


def tool_update_ticket(params: dict) -> dict:
    ticket_id = params.get("ticket_id")
    status    = params.get("status")
    response  = params.get("response")

    if not ticket_id:
        raise ValueError("ticket_id required")

    conn = _pg()
    cur = conn.cursor()

    try:
        updates = ["updated_at = NOW()"]
        args = []
        if status:
            updates.append("status = %s")
            args.append(status)
        if response:
            updates.append("response = %s")
            args.append(response)

        args.append(ticket_id)
        cur.execute(f"UPDATE crm_tickets SET {', '.join(updates)} WHERE id = %s", args)
        conn.commit()
        return {"status": "updated", "ticket_id": ticket_id}
    finally:
        cur.close()
        conn.close()


def tool_list_tickets(params: dict) -> list:
    status = params.get("status", "open")
    conn = _pg()
    cur = conn.cursor()

    try:
        if status:
            cur.execute("""
                SELECT t.id, t.subject, t.body, t.priority, t.status, t.response,
                       c.email, c.name, t.created_at
                FROM crm_tickets t
                LEFT JOIN crm_contacts c ON c.id = t.contact_id
                WHERE t.status = %s
                ORDER BY t.created_at DESC LIMIT 50
            """, (status,))
        else:
            cur.execute("""
                SELECT t.id, t.subject, t.body, t.priority, t.status, t.response,
                       c.email, c.name, t.created_at
                FROM crm_tickets t
                LEFT JOIN crm_contacts c ON c.id = t.contact_id
                ORDER BY t.created_at DESC LIMIT 50
            """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def tool_create_payment_intent(params: dict) -> dict:
    """
    Creates a Stripe PaymentIntent for chat-based sales.
    Returns client_secret for frontend to complete payment.
    """
    if not STRIPE_KEY:
        return {"error": "Stripe not configured. Set STRIPE_SECRET_KEY."}

    try:
        import stripe
        stripe.api_key = STRIPE_KEY

        amount_cents = int(params.get("amount_cents", 0))
        description  = params.get("description", "Silent Empire Service")
        contact_id   = params.get("contact_id", "")

        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")

        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            description=description,
            metadata={"contact_id": contact_id}
        )

        return {
            "client_secret": intent.client_secret,
            "id": intent.id,
            "amount_cents": amount_cents,
            "status": intent.status,
        }
    except Exception as e:
        return {"error": str(e)}


def tool_record_payment(params: dict) -> dict:
    contact_id   = params.get("contact_id", "")
    amount_cents = int(params.get("amount_cents", 0))
    product      = params.get("product", "")
    reference    = params.get("reference", "")

    conn = _pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO crm_payments (contact_id, amount_cents, product, reference)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (contact_id, amount_cents, product, reference))

        payment_id = cur.fetchone()[0]

        # Upgrade contact status to 'client'
        if contact_id:
            cur.execute("""
                UPDATE crm_contacts SET status = 'client', updated_at = NOW()
                WHERE id = %s
            """, (contact_id,))

        conn.commit()
        return {"status": "recorded", "payment_id": payment_id}
    finally:
        cur.close()
        conn.close()


def tool_get_client_context(params: dict) -> dict:
    """
    Returns the AI context for a client's chat session.
    Includes guardrails, persona, system prompt, history summary.
    This is what powers the CLIENT-SIDE portal with different context
    than the owner Mission Control.
    """
    client_id = params.get("client_id")
    if not client_id:
        raise ValueError("client_id required")

    conn = _pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT guardrails, persona, system_prompt, history_summary
            FROM client_contexts
            WHERE client_id = %s
        """, (client_id,))
        row = cur.fetchone()
        if not row:
            # Default context for new clients
            return {
                "guardrails": {"scope": "client_support", "no_internal_access": True},
                "persona": "Helpful AI assistant for client support",
                "system_prompt": "You are a helpful AI assistant. Help the client with their questions and needs.",
                "history_summary": "",
            }
        return {
            "guardrails": row[0] or {},
            "persona": row[1] or "",
            "system_prompt": row[2] or "",
            "history_summary": row[3] or "",
        }
    finally:
        cur.close()
        conn.close()


def tool_set_client_context(params: dict) -> dict:
    client_id     = params.get("client_id")
    guardrails    = params.get("guardrails", {})
    persona       = params.get("persona", "")
    system_prompt = params.get("system_prompt", "")
    history_summary = params.get("history_summary", "")

    if not client_id:
        raise ValueError("client_id required")

    conn = _pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO client_contexts (client_id, guardrails, persona, system_prompt, history_summary, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (client_id)
            DO UPDATE SET
                guardrails      = EXCLUDED.guardrails,
                persona         = EXCLUDED.persona,
                system_prompt   = EXCLUDED.system_prompt,
                history_summary = EXCLUDED.history_summary,
                updated_at      = NOW()
        """, (client_id, json.dumps(guardrails), persona, system_prompt, history_summary))
        conn.commit()
        return {"status": "updated", "client_id": client_id}
    finally:
        cur.close()
        conn.close()


# --------------------------------------------------
# SERVER ASSEMBLY
# --------------------------------------------------

class CRMServer(MCPServer):
    def __init__(self):
        super().__init__("crm")
        self.register_tool("upsert_contact",        tool_upsert_contact)
        self.register_tool("get_contact",           tool_get_contact)
        self.register_tool("list_contacts",         tool_list_contacts)
        self.register_tool("create_deal",           tool_create_deal)
        self.register_tool("update_deal",           tool_update_deal)
        self.register_tool("get_pipeline",          tool_get_pipeline)
        self.register_tool("create_ticket",         tool_create_ticket)
        self.register_tool("update_ticket",         tool_update_ticket)
        self.register_tool("list_tickets",          tool_list_tickets)
        self.register_tool("create_payment_intent", tool_create_payment_intent)
        self.register_tool("record_payment",        tool_record_payment)
        self.register_tool("get_client_context",    tool_get_client_context)
        self.register_tool("set_client_context",    tool_set_client_context)


if __name__ == "__main__":
    _init_crm_tables()
    server = CRMServer()
    server.run()
