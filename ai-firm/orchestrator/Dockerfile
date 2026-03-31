FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY orchestrator /app/orchestrator

ENV PYTHONPATH=/app

CMD ["python", "-u", "orchestrator/main.py"]
