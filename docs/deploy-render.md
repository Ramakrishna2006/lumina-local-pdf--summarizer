# Deploy Lumina on Render

Render runs Lumina as one web service: the React interface and the FastAPI
backend share one URL.

> **Privacy note.** On your own PC Lumina is fully local. Render cannot run
> Ollama, so the hosted copy sends questions and document excerpts to the
> online AI you choose (Groq, OpenAI, OpenRouter …). Do not upload sensitive
> files to the hosted copy, and always set `ACCESS_PASSWORD`.

## Files that make it work

| File | Purpose |
|------|---------|
| `Dockerfile` | Builds the React UI (Node 20), then the Python 3.12 backend with Tesseract OCR |
| `.dockerignore` | Keeps `.env`, `.venv`, `node_modules` and `storage/` out of the image |
| `render.yaml` | Render Blueprint: Docker service, health check, environment variables |
| `requirements.txt` | Root pointer to `backend/requirements.txt` (for Render's Python runtime) |
| `.python-version` | Pins Python 3.12 (Render's default 3.14 is too new for some libraries) |

## Option A – fix an existing *Python* service (quickest)

Render dashboard → your service → **Settings**:

| Setting | Value |
|---------|-------|
| Build Command | `pip install -r requirements.txt && cd frontend && npm install && npm run build` |
| Start Command | `python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/ping` |

(OCR of scanned PDFs needs Tesseract, which only the Docker option includes.)

## Option B – Blueprint with Docker (recommended)

1. Render dashboard → **New → Blueprint** → choose this GitHub repository.
2. Render reads `render.yaml` and asks for the secret values.
3. Click **Apply**. The first build takes about 5–8 minutes.

## Environment variables (Settings → Environment)

| Key | Value |
|-----|-------|
| `LLM_PROVIDER` | `openai` |
| `OPENAI_BASE_URL` | e.g. `https://api.groq.com/openai/v1` |
| `OPENAI_MODEL` | e.g. `llama-3.1-8b-instant` |
| `OPENAI_API_KEY` | your key — **typed only in Render, never committed** |
| `ACCESS_PASSWORD` | a password for the lock screen |
| `IMAGE_PROVIDER` | `pollinations` (free online images, no key) |
| `LLM_WARMUP_ON_STARTUP` | `false` |
| `OPENAI_EMBEDDING_MODEL` | leave empty (keyword search) |

## Good to know (free plan)

- The service sleeps after 15 minutes without visitors; the first visit then takes about a minute.
- The disk is temporary: uploaded documents and chats disappear on every redeploy or restart.
- Check it works: open `https://<your-service>.onrender.com/api/ping` → `{"status":"ok"}`.

## Troubleshooting

| Log message | Fix |
|-------------|-----|
| `Could not open requirements file: requirements.txt` | Pull the latest code (root `requirements.txt` now exists) or use the build command above |
| `Using Python version 3.14…` then build errors | Make sure `.python-version` is in the repo, or add env var `PYTHON_VERSION=3.12.7` |
| Page loads but answers fail | `OPENAI_API_KEY`, `OPENAI_BASE_URL` or `OPENAI_MODEL` is wrong |
| `No open ports detected` | Start command must use `--host 0.0.0.0 --port $PORT` |
