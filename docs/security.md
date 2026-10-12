# Security and privacy

* **Local by default.** Documents, extracted text, vectors and chats are stored in
  `storage/` on your computer. The LLM runs in Ollama (or another local server)
  on your computer. Fonts are bundled, so the UI makes no third-party requests.
* **OpenAI-compatible provider.** If you set `LLM_PROVIDER=openai` and point
  `OPENAI_BASE_URL` at a *hosted* service, the retrieved passages and your
  question are sent to that service. Local servers (LM Studio, llama.cpp) stay
  on your machine.
* **Web mode is the exception.** When you switch the composer to *Web*, your
  question (not your files) is sent to public search APIs (GitHub, GitLab,
  Stack Overflow, arXiv, Hugging Face, DuckDuckGo or Google). Turn it off with
  `WEB_RESEARCH_ENABLED=false`.
* **Uploads** are checked by extension allow-list, size limit and (for PDFs) file
  signature, and are stored under random UUID names. The original name is only
  kept as display text.
* **Prompt injection.** Document text is treated as data; the system prompt tells
  the model never to follow instructions found inside documents. The document
  cannot choose the model, endpoint, file paths or settings.
* **Safe rendering.** The UI renders Markdown into React elements – it never uses
  `innerHTML`, so text from a document or model cannot run scripts.
* **Deleting a document** removes the file, its chunks, its vector index and any
  chat that used only that document.
* **Secrets** (`OPENAI_API_KEY`, `GOOGLE_API_KEY` …) belong in `.env`, which is
  git-ignored together with `storage/`. Run `python scripts/secret_scan.py`
  before pushing – it fails if a key is found in the code.
* **Image mode** runs on your computer. Prompts are not sent anywhere; the
  model is downloaded once from Hugging Face. Images are saved in
  `storage/images/` (git-ignored) under random names, and the image route only
  accepts those 32-character ids, so it cannot be used to read other files.
* **Access password.** This build is meant for **one trusted local user**.
  Before sharing it on a network or the internet (for example with a Cloudflare
  Tunnel), set `ACCESS_PASSWORD` in `.env`: every `/api` route then needs a
  login cookie (an HMAC of the password, HttpOnly, 30 days), wrong passwords are
  slowed down, and visitors see a lock screen. Use a long password and keep it
  only in `.env`.
