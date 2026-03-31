FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/systems /app
COPY shared /app/shared

ENV PYTHONPATH=/app

CMD ["python", "-u", "main.py"]
