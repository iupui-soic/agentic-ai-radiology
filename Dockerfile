FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install the package itself for the entry-point scripts
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/src

EXPOSE 8001

# AGENT_MODULE can be overridden by Cloud Run env vars
ENV AGENT_MODULE=critcom_agent.app:a2a_app
ENV PORT=8001

CMD ["sh", "-c", "uvicorn ${AGENT_MODULE} --host 0.0.0.0 --port ${PORT}"]
