FROM python:3.11-slim

# Install Docker CLI (for docker commands)
RUN apt-get update && apt-get install -y \
    docker.io \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ai-firm

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /ai-firm/shared
COPY tool_executor /ai-firm/tool_executor

ENV PYTHONPATH=/ai-firm

CMD ["python", "-u", "tool_executor/main.py"]
