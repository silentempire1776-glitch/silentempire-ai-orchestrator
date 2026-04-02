# =========================================================
# Code Agent Dockerfile
# Save as: /srv/silentempire/ai-firm/agents/code/Dockerfile
# =========================================================
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/code /app
COPY shared /app/shared
COPY shared/job_runner.py /app/job_runner.py
COPY shared/config_loader.py /app/config_loader.py

ENV PYTHONPATH=/app

CMD ["python", "-u", "main.py"]
