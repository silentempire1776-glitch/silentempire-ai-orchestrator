#!/usr/bin/env python3
from pathlib import Path

MODELS = Path("/srv/silentempire/app/models.py")

CHAIN_BLOCK = r'''
# ==========================================
# CHAIN EXECUTION (Orchestrator Chains)
# ==========================================
# NOTE: Added to support /chains/* routes (chains_api.py)

import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

class ChainRun(Base):
    __tablename__ = "chain_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String, default="queued", nullable=False)  # queued|running|completed|failed
    target = Column(String, nullable=True)
    product = Column(String, nullable=True)
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class ChainStep(Base):
    __tablename__ = "chain_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain_id = Column(UUID(as_uuid=True), ForeignKey("chain_runs.id", ondelete="CASCADE"), index=True, nullable=False)

    step_name = Column(String, nullable=False)   # research|revenue|sales|growth|product|legal|systems|ceo_summary
    agent = Column(String, nullable=True)
    model = Column(String, nullable=True)

    status = Column(String, default="queued", nullable=False)  # queued|running|completed|failed
    input_payload = Column(JSON, nullable=True)
    output = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
'''

def main():
    if not MODELS.exists():
        raise SystemExit(f"Missing {MODELS}")

    txt = MODELS.read_text()

    if "class ChainRun" in txt or "class ChainStep" in txt:
        print("OK: chain models already present")
        return

    # backup
    bak = MODELS.with_suffix(".py.bak")
    bak.write_text(txt)
    print(f"Backup -> {bak}")

    MODELS.write_text(txt + "\n" + CHAIN_BLOCK + "\n")
    print("Patched models.py with ChainRun/ChainStep")

if __name__ == "__main__":
    main()
