# =========================================================
# Voice Agent Dockerfile
# Save as: /srv/silentempire/ai-firm/agents/voice/Dockerfile
# =========================================================
FROM python:3.11-slim

WORKDIR /app

# Base requirements
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Voice provider packages (installed but only used if keys are set)
# twilio: outbound/inbound calling
# vonage: alternative telephony
# All are lightweight — install all so no rebuild needed when switching
RUN pip install --no-cache-dir \
    twilio \
    vonage \
    && echo "Voice provider packages installed"

COPY agents/voice /app
COPY shared /app/shared

ENV PYTHONPATH=/app

CMD ["python", "-u", "main.py"]
