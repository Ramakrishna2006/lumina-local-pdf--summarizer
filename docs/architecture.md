# Architecture

```
 Browser (React + Vite, port 5173)
        │  /api/*  (Vite proxy)
        ▼
 FastAPI backend (port 5001) ─────────────► SQLite  storage/app.db
        │                                   (documents, chunks, chats)
        │ extract ─► chunk ─► embed
        │                     │
        │                     ▼
        │             storage/rag/<id>.npy  (vectors, cached in RAM)
        ▼
 Ollama (port 11434)              or any OpenAI-compatible server
   • chat model       e.g. llama3.2:3b      (LM Studio, llama.cpp, vLLM …)
   • embedding model  e.g. embeddinggemma

 Image mode (optional, inside the backend – Ollama is not used)
   POST /api/images/generate
        │  one image at a time (asyncio lock), in a worker thread
        ▼
   SD-Turbo text encoder ─► UNet (1 step) ─► TAESD tiny decoder ─► storage/images/<id>.png
```

With `npm run build`, the backend also serves the built interface from
`frontend/dist`, so the whole app runs on port 5001 ("one-port mode").

## Upload pipeline (background task)

1. **Validate** – extension allow-list, size limit, `%PDF-` signature, UUID file name.
2. **Extract** – runs in a worker thread so the API stays responsive.
   * PDF: PyMuPDF native text (automatic fallback to pypdfium2 or pypdf); pages with little text are rendered and OCR'd with
     Tesseract **in parallel, in small batches** (low memory use).
   * DOCX / PPTX / XLSX / XLS / CSV / TXT / MD / JSON / XML / YAML / HTML / source code / images.
3. **Chunk** – paragraph/sentence-aware chunks (`CHUNK_SIZE`, `CHUNK_OVERLAP`).
4. **Embed** – chunks are embedded in batches with the Ollama embedding model and
   saved as a normalised NumPy matrix. If the embedding model is missing, the app
   falls back to keyword (BM25) search instead of failing.

## Asking a question

0. **Answer cache** – if the same question was already asked about the same
   documents with the same style, language, model and chat history, the stored
   answer is returned instantly (no model call). The cache is cleared for a
   document whenever it is deleted or re-processed.
1. The question (plus the previous question for short follow-ups like "why?") is
   embedded once (cached).
   The question is embedded **at the same time** as the document indexes are
   loaded (asyncio task), so the two waits overlap.
2. Hybrid score = `0.8 × cosine similarity + 0.2 × BM25` across every selected
   document; every document contributes at least its best passage.
3. The best passages (max `RAG_MAX_CONTEXT_CHARS`) + recent chat history go to the
   chat model with a style-specific system prompt.
4. Tokens are streamed to the browser with Server-Sent Events: `start → sources →
   token… → done (timing stats)`.

## Why it is fast

| Technique | Effect |
|---|---|
| Shared pooled HTTP client to Ollama | no new connection per request |
| Model warm-up on startup + `keep_alive` | first answer does not wait for model loading |
| Retrieval done once per answer (was twice) | half the embedding work |
| In-RAM index cache + pre-tokenised chunks | no disk reads per question |
| Smaller chunks, tighter context (7 000 chars) | much faster prompt processing on CPU |
| Answer styles cap generated tokens | "Concise" answers finish in a fraction of the time |
| Streaming summaries from evenly sampled chunks | one LLM call that covers the whole document |
| Parallel OCR, extraction in threads | scanned PDFs process several times faster |
| SQLite WAL mode | reads never wait for background writes |
| Answer cache (LRU, in RAM) | repeated questions are answered instantly |
| Query embedding runs in parallel with index loading | lower time-to-first-word |
| Missing embedding model remembered for 5 minutes | no failed embedding call on every question |
| "Balanced" default style (≈500 tokens) | complete answers without the cost of "Detailed" |
| Frontend batches streamed tokens per animation frame | smooth UI even with fast models |
| Document is "ready" right after chunking; vectors are built in the background | uploads usable in seconds instead of minutes on CPU |
| Background embedding runs one document at a time, in small batches | the first file gets smart search first; questions are not stuck behind a big batch |
| Background embedding pauses while an answer or summary is written | the AI model gets the whole CPU when you are waiting |
| Question embedding is skipped when no selected file has vectors yet | no wasted call during background indexing |
| Deleting a file cancels its background work | no wasted CPU and no orphaned index files |
| Model "slot": one request at a time, questions before background work | a CPU-only PC is never asked to run several generations at once; queue time does not count towards `LLM_TIMEOUT` |
| Suggested questions built from key terms (`services/suggest.py`), not by the LLM | selecting a document no longer puts a 1–2 minute job in front of your question |
| "Summarize this" questions use evenly spaced chunks from the whole file | complete summaries without a second model call |
| Summary context sized to fit `LLM_NUM_CTX` | Ollama never silently cuts off the start of the prompt |
| Smaller default context (5 000 chars, top-5 passages) | the first word appears sooner on CPU |
| Speed profile per model (measured at start-up and from every answer's `prompt_eval`/`eval` timings) | Lumina knows how many tokens/s *this* PC reads and writes |
| `answer_budget()` sizes only the *reading* to `READ_TARGET_SECONDS` (answers keep full length) | the first word appears much sooner on a slow CPU, answers stay complete |
| `focus_text()` keeps the sentences that match the question when passages must be shortened | same information in less text – faster reading without losing facts |
| "No padding" rule in the system prompt (no preamble, no restating, no repetition) | every written word carries information |
| Optional `within_time()` limit (`ANSWER_HARD_LIMIT_SECONDS`, off by default) | can cap very long answers if you prefer speed over completeness |
| Chat history trimmed to short excerpts | follow-up questions do not re-read whole previous answers |
| `LLM_KEEP_ALIVE=2h` | the model is not unloaded between questions (re-loading costs 10–30 s) |

## Frontend animation

The interface is calm on purpose. While Lumina works, its four-petal mark
(`components/Mark.jsx`) slowly turns and breathes and the status text has a
light "shimmer". Answers are revealed by `useSmoothText()` in `Message.jsx`:
the words that arrive from the model in bursts are shown at an even pace
(always catching up within a few frames), and every new paragraph, list item
or table row fades and rises in (`@keyframes blockIn`). Everything respects
the operating system's *reduce motion* setting and the *Animations* switch
in ⚙ Settings (`data-motion="off"`).

## Image mode

`backend/app/services/image_gen.py` turns a text prompt into a PNG.

1. **Provider** – `IMAGE_PROVIDER=local` runs **SD-Turbo** with Hugging Face
   `diffusers` on this PC; `openai` calls any `/v1/images/generations` server
   (for example Ollama's image models, which today only run on macOS); `off`
   refuses requests and the interface hides the **Image** button.
2. **Optional libraries** – PyTorch, diffusers, transformers and accelerate are
   *not* in `requirements.txt`. If they are missing, `/api/images/status`
   reports them and a request returns a clear "install these" message instead
   of crashing.
3. **Loading** – the pipeline is loaded once and kept in memory. With
   `IMAGE_PRELOAD=true` this happens in the background at start-up, so the
   first request does not wait. The half-size `fp16` files are downloaded and
   converted to float32 on a CPU.
4. **Speed on a CPU**
   * SD-Turbo needs only **1 drawing step** (`IMAGE_STEPS=1`, no guidance).
   * The normal image decoder (VAE) is replaced by **TAESD**, a tiny decoder
     that is many times faster on a CPU (`IMAGE_FAST_DECODER=true`).
   * Default size **384 × 384** (`IMAGE_SIZE`; 256 is about twice as fast).
   * One image at a time, so it never competes with itself for the CPU.
5. **Saving** – the image is saved as `storage/images/<random id>.png` and
   served by `GET /api/images/{id}`; the id must be 32 hex characters, so
   no other file can be read through this route.

## Access password (optional)

When `ACCESS_PASSWORD` is set, a middleware blocks every `/api` route (and the
API docs) until the browser has logged in at `/api/auth/login`. The login sets
an HttpOnly cookie that holds an HMAC of the password – never the password
itself – for 30 days. Wrong passwords wait one second to slow down guessing.
The interface shows a lock screen (`components/Gate.jsx`) until then.
