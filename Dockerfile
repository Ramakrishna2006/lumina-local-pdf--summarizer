# Backend image (FastAPI + OCR). Ollama runs separately (on the host or the
# "ollama" service in docker-compose.yml).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY scripts scripts
RUN mkdir -p storage

ENV HOST=0.0.0.0 PORT=5001 TESSERACT_CMD=/usr/bin/tesseract
EXPOSE 5001
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "5001"]
