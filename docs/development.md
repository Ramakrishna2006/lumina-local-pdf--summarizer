# Development

## Run the tests

```bash
pip install -r backend/requirements-dev.txt
pytest backend/tests -q          # 38 tests – fake Ollama and fake image model, nothing is downloaded
ruff check backend --select E,F,W,B --ignore E501,B008
python scripts/secret_scan.py    # run before every push
```

Frontend:

```bash
cd frontend
npm run build     # production build in frontend/dist
npm run lint
```

## Project layout

```
backend/app/main.py                 API routes and SSE streaming
backend/app/core/config.py          every setting (read from .env)
backend/app/services/llm.py         Ollama + OpenAI-compatible client, prompts, styles, languages
backend/app/services/answer_cache.py instant answers for repeated questions
backend/app/services/rag_service.py embeddings, hybrid search, caching
backend/app/services/suggest.py     instant suggested questions (no LLM call)
backend/app/services/summary.py     streaming summaries
backend/app/services/web_research.py public web search + synthesis
backend/app/services/image_gen.py   Image mode (SD-Turbo / OpenAI-compatible image server)
backend/app/services/extraction/    one extractor per file type
frontend/src/App.jsx                application state and streaming
frontend/src/components/Composer.jsx message box with the Documents / Web / Image modes
frontend/src/components/Gate.jsx    password lock screen (ACCESS_PASSWORD)
frontend/src/components/            Sidebar, Message, DocDrawer, Welcome, Mark…
frontend/src/styles.css             white/black + indigo design tokens, light + dark themes
```

## Useful scripts

| Command | What it does |
|---|---|
| `python scripts/reindex_all_rag.py` | re-chunk and re-embed every document (after changing chunk size or embedding model) |
| `python scripts/cleanup.py` | delete temporary files older than one hour |
| `python scripts/secret_scan.py` | look for API keys accidentally left in code |

## Working on Image mode

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r backend/requirements-image.txt
python -c "import torch, diffusers; print('ok')"
```

* The tests never load the real model: `backend/tests/test_images.py` swaps in
  a fake painter, and `conftest.py` sets `IMAGE_PRELOAD=false`.
* To check the status of a running backend: `curl http://127.0.0.1:5001/api/images/status`.
* To try another model, set `IMAGE_MODEL` to any Hugging Face text-to-image model
  that `diffusers` can load (bigger models need more steps: raise `IMAGE_STEPS`).
