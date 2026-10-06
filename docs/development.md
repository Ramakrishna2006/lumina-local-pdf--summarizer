# Development

## Run the tests

```bash
pip install -r backend/requirements-dev.txt
pytest backend/tests -q          # uses a fake Ollama – no model needed
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
backend/app/services/extraction/    one extractor per file type
frontend/src/App.jsx                application state and streaming
frontend/src/components/Backdrop.jsx animated canvas background
frontend/src/components/            Sidebar, Message, Composer, DocDrawer, Welcome…
frontend/src/styles.css             white/black + indigo design tokens, light + dark themes
```

## Useful scripts

| Command | What it does |
|---|---|
| `python scripts/reindex_all_rag.py` | re-chunk and re-embed every document (after changing chunk size or embedding model) |
| `python scripts/cleanup.py` | delete temporary files older than one hour |
| `python scripts/secret_scan.py` | look for API keys accidentally left in code |
