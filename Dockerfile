FROM python:3.12-slim-bookworm AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

# Runtime tools available to the agent at execution time
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    curl wget git jq \
    unzip zip \
    build-essential \
    bash \
    sudo \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM deps AS final
COPY src/ ./src/

ENV DEEP_AGENT_WORKSPACE=/workspace/agent_files
RUN mkdir -p logs "${DEEP_AGENT_WORKSPACE}"

CMD ["python", "-m", "src.main"]
