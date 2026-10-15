# One image, two entry points (API and UI), see docker-compose.yml.
# Ollama is NOT in the image: it runs on the host with the GPU, reached via host.docker.internal.
FROM python:3.11-slim

# libgomp1: OpenMP runtime PaddlePaddle needs. libglib2.0-0: OpenCV (headless) needs it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, code second: editing code then reuses the cached ~1 GB pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

# Run as a normal user, not root. data/ and models/ are mounted volumes (compose).
RUN useradd --create-home app && mkdir -p /app/data /app/models && chown -R app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    OLLAMA_URL=http://host.docker.internal:11434 \
    RECEIPTS_DB=/app/data/db/receipts.db \
    RECEIPTS_UPLOADS=/app/data/raw

EXPOSE 8765 8501
CMD ["uvicorn", "receipt_ai.api:app", "--host", "0.0.0.0", "--port", "8765"]
