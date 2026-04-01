FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/legal /app
COPY shared /app/shared
COPY shared/job_runner.py /app/job_runner.py

ENV PYTHONPATH=/app

CMD ["python", "-u", "main.py"]
