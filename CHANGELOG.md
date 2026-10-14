# Changelog

All notable changes to Lumina. Newest first.

## 7.2.0 – Code mode, colours, images on Render

**Added**
- **Code mode** – a fourth button in the message box (Documents · **Code** · Web · Image). Ask for code in any language or paste an error; answers stream with **syntax highlighting**, **Copy** and **Download** on every code block (file names like `app/main.py` are detected), and run commands for your OS. Follow-up questions remember the conversation. `POST /api/code/stream`.
- **Change colours** – ⚙ Settings → *Change colours…*: 9 accent colours or any custom colour, gradients, light/dark/system, custom background/sidebar/bubble/border colours, compact spacing. Text contrast is checked automatically; the choice is saved in the browser.
- **Image generation on Render** – new `IMAGE_PROVIDER=pollinations`: the free pollinations.ai service (no key, no PyTorch). The message box says when a description is sent online. `render.yaml` now uses it.

## 7.1.1 – Deploy on Render

**Added**
- Render deployment: multi-stage `Dockerfile` (builds the React UI, then the backend; UI + API on one port), `.dockerignore`, `render.yaml` Blueprint, root `requirements.txt`, `.python-version` (3.12) and the guide [docs/deploy-render.md](docs/deploy-render.md).
- `GET /api/ping` – tiny health check that stays open when `ACCESS_PASSWORD` is set.

**Removed**
- `frontend/vercel.json` (Vercel is no longer used).

## 7.1.0 – Image mode and access password

**Added**
- **Image mode** – a third button in the message box (Documents · Web · **Image**). Describe a picture and Lumina paints it on your computer with Stable Diffusion **SD-Turbo** (1 drawing step), with a seconds counter, **Download** (PNG) and **Another version**. Images are saved in `storage/images/`.
- Optional install: `backend/requirements-image.txt` (PyTorch + diffusers), or `scripts/setup.ps1 -WithImages` / `scripts/setup.sh --with-images`.
- Fast settings for CPUs: tiny **TAESD** decoder, **background preload** of the model at start-up, default size **384 × 384** (`IMAGE_SIZE=256` is faster still).
- `IMAGE_PROVIDER=off` removes the Image button; `IMAGE_PROVIDER=openai` uses any OpenAI-compatible image server (e.g. Ollama image models on macOS).
- **Access password** (`ACCESS_PASSWORD`) with a lock screen, for sharing Lumina on the internet (e.g. Cloudflare Tunnel). The browser stays unlocked for 30 days; the cookie never contains the password.
- New API routes: `/api/images/status`, `/api/images/generate`, `/api/images/{id}`, `/api/auth/status`, `/api/auth/login`, `/api/auth/logout`.
- Docs: interface guide, Image mode step-by-step guide, screenshots, image troubleshooting.

**Changed**
- Dockerfile uses the `$PORT` given by hosting sites (default 5001).
- 38 automated tests (image and password tests use fakes – nothing is downloaded).

**Fixed**
- Lint error (duplicate words in `suggest.py`) that failed the GitHub check.

## 7.0.0 – Claude-style interface, complete answers sooner
- White and black "paper & ink" interface with one indigo accent, centred conversation, serif answers that flow in smoothly, animated Lumina mark, collapsible sidebar, light and dark themes.
- Answers always keep their full length; on a slow PC Lumina reads only the sentences that match the question so the first words appear much sooner.
- Speed profile per model, model queue (questions before background work), background smart search, instant suggested questions, answer cache.
- Effectiveness test (`scripts/evaluate.py`) and the test-case guide (`docs/TEST_CASES.md`).

## 6.x and earlier
- Renamed from *local-pdf-llm-summarizer* to **Lumina**; support for Word, PowerPoint, Excel, HTML, code and scanned files; hybrid search; summaries, quizzes and study notes; Web mode; 14 answer languages.
