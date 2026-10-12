# Lumina – test cases

Three levels of testing, from fastest to most realistic.

| Level | What it checks | How long | Needs a real AI model? |
|---|---|---|---|
| 1. Automated tests (`pytest`) | the code logic: uploads, search, streaming, caching, speed planning, deleting… | ~10 s | no (uses a fake model) |
| 2. Effectiveness test (`scripts/evaluate.py`) | the **quality and speed of real answers on your computer** | 5–25 min | yes (Ollama) |
| 3. Manual checklist (below) | the interface: buttons, animations, themes, files | ~20 min | yes |

---

## 1. Automated tests

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt
pytest backend\tests -q
```

Expected: `38 passed`. The tests use a fake Ollama server and a fake image painter, so they run without any model. They cover:

| Area | What is tested |
|---|---|
| Files | PDF / text / code extraction, upload validation (wrong type, empty, fake PDF), deleting files, deleting a file *while it is still being read* |
| Search | hybrid search, keyword fallback when the embedding model is missing, plural/verb forms ("firewalls" finds "firewall"), keeping only the relevant sentences, "summarize" questions using the whole document |
| Answers | streaming, multi-document chats, follow-up memory, regenerate, answer styles, languages, word limits only when asked, answer cache |
| Speed | the model queue (questions before background work), background indexing pauses during answers, speed planning keeps full answer length, optional time limit |
| Images | painting and downloading a PNG, size rounding, missing libraries → clear message, unsafe ids rejected, `IMAGE_PROVIDER=off`, OpenAI-compatible image servers, background preload |
| Access | password lock: blocked without login, wrong password refused, cookie never contains the password, logout |
| Other | summaries and download, instant suggested questions (no AI call), web research, OpenAI-compatible servers |

---

## 2. Effectiveness test on your computer

Start the backend (and Ollama), then in a second window:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\evaluate.py --quick     # 6 core tests
python scripts\evaluate.py             # all 15 tests
```

The script uploads a small test document with known facts, asks real questions with your real model, scores the answers and writes **`evaluation-results.md`** (score, timings and every answer). The test document is deleted afterwards.

| ID | Checks | Question | Passes when |
|---|---|---|---|
| T01 | Upload speed | – | the file is ready in under 60 s |
| T02 | Accuracy | What does the CIA triad stand for? | answer has *confidentiality, integrity, availability* |
| T03 | Follow-up memory | Why is it important for a security policy? | understands "it" = CIA triad |
| T04 | Accuracy (numbers) | Which port does HTTPS use, and SSH? | answer has *443* and *22* |
| T05 | Honesty | Who is the principal of the college? | says the document does not contain it (no made-up name) |
| T06 | Whole document | Give me a summary of this document | mentions facts from the **first and last** chapter |
| T07 | Table style | Compare symmetric and asymmetric encryption | a Markdown table with AES and RSA |
| T08 | Explain simply | Explain a DoS attack | mentions flooding / traffic |
| T09 | Bullet points | List the common attacks described | at least 3 of the 4 attacks |
| T10 | Detailed | How does HTTPS use both kinds of encryption? | session key + asymmetric/public key |
| T11 | Exact quotes | What is a hash function? | SHA-256 / fixed-length digest |
| T12 | Study notes | Study notes about firewalls and IDS | covers both |
| T13 | Answer cache | the T02 question again | answered instantly |
| T14 | Completeness | – | no answer stops in the middle of a sentence |
| T15 | Citations | – | answers show their source passages |

**How to read the result**

- **12–15 passed** – the model and Lumina work well together.
- **9–11** – fine for most use; look at the failed answers in `evaluation-results.md`.
- **below 9** – try a stronger model (e.g. `qwen2.5:3b`, `llama3.1:8b` if you have 16 GB RAM) or check that `ollama pull embeddinggemma` was run.
- **Speed**: "average first word" shows how long you wait before text appears; "average answer" is the full time. Compare models by running the script once per model (choose the model in the top bar, or set `OLLAMA_MODEL` in `.env`).

---

## 3. Manual checklist

Use a real PDF, a PowerPoint and a Word file of your own. Mark each row ✅ or ❌.

### Setup and status

| ID | Steps | Expected result |
|---|---|---|
| M01 | Start Ollama, the backend and the frontend; open http://127.0.0.1:5173 | page loads; greeting "Good morning/afternoon/evening"; sidebar shows a green dot and "Local AI · Live" |
| M02 | Stop Ollama, wait 20 s | status turns red ("Ollama is not reachable"); start Ollama again → green |
| M03 | Look at the backend window after start-up | line "Speed of llama3.2:3b on this PC: reads … tokens/s, writes … tokens/s" |

### Files

| ID | Steps | Expected result |
|---|---|---|
| M04 | Drag a PDF onto the window | drop overlay appears; file shows progress, then "ready" toast within seconds |
| M05 | Click **+** and add a .pptx and a .docx | both appear in the Library with page counts |
| M06 | Upload a scanned PDF or a photo of a page (Tesseract installed) | text is found ("OCR" in the file details) |
| M07 | Upload a .exe or an empty file | clear error message, nothing added |
| M08 | Delete a file while it is still being read | it disappears; no error in the backend window |
| M09 | Click the eye icon on a file → *Extracted text* | the text of the document is shown |

### Questions and answers

| ID | Steps | Expected result |
|---|---|---|
| M10 | Tick one file, ask a question whose answer is in the file | correct answer; numbered source chips; "First words … · done in …" below |
| M11 | Ask something that is **not** in the file | Lumina says the document does not contain it |
| M12 | Ask a follow-up: "explain more" / "why?" | answer continues the same topic |
| M13 | Ask "give a summary of this ppt" | summary covers the start **and** the end of the file |
| M14 | Tick 3 files, ask "compare the main ideas" | answer uses all three (sources from each file) |
| M15 | Try every style: Balanced, Concise, Detailed, Bullet points, Explain simply, Study notes, Table, Quotes | each answer has the matching form (table, bullets, quotes…), complete, not cut off |
| M16 | Ask the same question again in a new chat | answered instantly ("Instant – answered from memory") |
| M17 | Click **Stop** while an answer is being written | writing stops at once; the partial answer stays |
| M18 | Click a source chip | the exact passage appears below |
| M19 | ⚙ Settings → Answer language: Hindi (or Tamil…), ask a question | answer is written in that language |
| M20 | Switch to **Web**, ask a general question (internet needed) | answer with web sources (links) |

### Summaries and study tools

| ID | Steps | Expected result |
|---|---|---|
| M21 | Top bar document button → *Summary* → Overview → Write summary | summary streams in; ".md" download works |
| M22 | Try TL;DR, Quiz, Key terms, FAQ | each has the right format (quiz with answers, glossary table…) |

### Speed

| ID | Steps | Expected result |
|---|---|---|
| M23 | Ask a question and watch the status | "Reading N passages · first words in about N s" counts down; text then flows in |
| M24 | Ask while a summary is being written | the question waits its turn and is answered – no timeout error |
| M25 | Upload 3 files at once and ask immediately | files are usable within seconds ("Adding smart search…" may show briefly) |
| M26 | Switch the model to `llama3.2:1b` (if installed) and ask the same question | first words and full answer arrive clearly faster |

### Interface

| ID | Steps | Expected result |
|---|---|---|
| M27 | Click the sun/moon icon | light ↔ dark theme, everything readable |
| M28 | Click the panel icon in the sidebar | sidebar hides; panel icon in the top bar shows it again |
| M29 | ⚙ Settings → Animations off | mark, shimmer and fade-ins stop |
| M30 | Make the browser window narrow (like a phone) | menu button appears, sidebar slides in, message box fits |
| M31 | Rename a chat (double-click), search chats, delete a chat | all work; the chat list updates |
| M32 | Press Ctrl+K | new chat; the message box is focused |

### Privacy

| ID | Steps | Expected result |
|---|---|---|
| M33 | Turn Wi-Fi off, ask a question in Documents mode | still works – everything runs locally |
| M34 | Run `python scripts\secret_scan.py` | "No obvious hard-coded secrets found" |
| M35 | Run `git status` before pushing | `.env`, `storage/`, `.venv/` and `node_modules/` are **not** listed |

### Image mode (optional – needs `backend/requirements-image.txt`)

| ID | Steps | Expected result |
|---|---|---|
| M36 | Without the image libraries, click **Image** and ask for "a red apple" | a clear message explaining how to install them – no crash |
| M37 | Install the libraries, restart, ask for "a watercolor lighthouse at sunset" | "Painting your image" with a seconds counter, then the picture (the first time downloads the model) |
| M38 | Click **Download** and **Another version** | a PNG file is saved · a new, different image is made |
| M39 | Put `IMAGE_PROVIDER=off` in `.env`, restart | the Image button is gone |
