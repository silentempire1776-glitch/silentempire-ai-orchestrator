from sqlalchemy import Column, String, Text, Integer, DateTime, Float, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.ext.declarative import declarative_base
import uuid
import datetime


Base = declarative_base()


# ==========================================
# JOB TABLE
# ==========================================

class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    type = Column(String, nullable=False)
    status = Column(String, default="pending", nullable=False)

    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    timeout_seconds = Column(Integer, default=60)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

    provider = Column(String, nullable=True)
    model_used = Column(String, nullable=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    estimated_cost_usd = Column(Float, nullable=True)


# ==========================================
# PROVIDER PRICING TABLE
# ==========================================

class ProviderPricing(Base):
    __tablename__ = "provider_pricing"

    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)

    input_cost_per_1k_tokens = Column(Float, nullable=False)
    output_cost_per_1k_tokens = Column(Float, nullable=False)

    last_updated = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_provider_model"),
    )


# ==========================================
# DAILY BUDGET CONTROL TABLE
# ==========================================

class BudgetControl(Base):
    __tablename__ = "budget_control"

    id = Column(Integer, primary_key=True)

    date = Column(String, nullable=False, unique=True)

    daily_limit_usd = Column(Float, nullable=False)
    current_spend_usd = Column(Float, nullable=False, default=0.0)

    is_locked = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

# ==========================================
# CHAT SESSIONS TABLE
# ==========================================
class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    name = Column(String, nullable=False, default="New Chat")
    messages = Column(JSON, nullable=True, default=list)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
