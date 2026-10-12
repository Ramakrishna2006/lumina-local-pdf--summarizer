# Lumina – one container: React UI + FastAPI backend on one port.
# Works locally (docker build -t lumina . && docker run -p 5001:5001 lumina)
# and on hosts like Render/Railway/Fly that pass the port in $PORT.

# ---------- stage 1: build the React frontend ----------
FROM node:20-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: Python backend ----------
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY scripts scripts
COPY --from=ui /ui/dist frontend/dist
RUN mkdir -p storage
ENV HOST=0.0.0.0 PORT=5001 TESSERACT_CMD=/usr/bin/tesseract PYTHONUNBUFFERED=1
EXPOSE 5001
CMD ["sh", "-c", "python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-5001}"]
