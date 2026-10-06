"""Scan the repository for accidentally hard-coded secrets before pushing to GitHub.

    python scripts/secret_scan.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "storage", ".idea", "__pycache__"}
PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*[\"'][^\"']{12,}[\"']"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),            # Google API key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                # OpenAI-style key
    re.compile(r"ghp_[A-Za-z0-9]{36}"),                # GitHub token
    re.compile(r"(?m)^(GOOGLE_API_KEY|GOOGLE_CSE_ID|OPENAI_API_KEY)=\S+"),  # filled-in keys in committed files
]

found = []
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
        continue
    if path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example" or path.suffix in {".png", ".jpg", ".pdf", ".db", ".npy", ".docx"}:
        continue
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        continue
    for pattern in PATTERNS:
        if pattern.search(text):
            found.append(str(path.relative_to(ROOT)))
            break

if found:
    print("Possible secrets found in:\n  " + "\n  ".join(found))
    sys.exit(1)
print("No obvious hard-coded secrets found.")
