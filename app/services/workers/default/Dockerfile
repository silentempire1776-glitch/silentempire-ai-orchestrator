FROM python:3.11-slim

WORKDIR /app

# Ensure project root is importable
ENV PYTHONPATH=/app

# Install worker dependencies
COPY services/workers/default/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire project
COPY . .

# Run correct worker
CMD ["python", "-u", "services/workers/default/worker.py"]
