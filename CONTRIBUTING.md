# Contributing to Lumina

Thanks for helping! A few simple rules keep the project healthy.

1. **Fork** the repository and create a branch: `git checkout -b feature/my-idea`
2. Set up the project (see the README) and make your change.
3. Run the checks:
   ```bash
   pytest backend/tests -q        # 38 tests, no model downloads
   ruff check backend --select E,F,W,B --ignore E501,B008
   python scripts/secret_scan.py
   cd frontend && npm run lint && npm run build
   ```
4. Commit with a clear message and open a pull request describing **what** and **why**.

## Please never commit

- your `.env` file, API keys or passwords
- anything inside `storage/` (your documents, database and indexes)
- `node_modules/`, `.venv/`, `frontend/dist/`

These are already in `.gitignore`; `scripts/secret_scan.py` double-checks for keys.

## Ideas that would be welcome

- more file types (EPUB, ODT, RTF)
- re-ranking of retrieved passages
- per-chat settings and pinned chats
- image-to-image (change an uploaded picture) and saving images in chat history
- translations of the interface

Working on **Image mode**? Install the optional libraries with
`pip install -r backend/requirements-image.txt` (after installing PyTorch), but
never commit downloaded models or anything in `storage/images/`.
