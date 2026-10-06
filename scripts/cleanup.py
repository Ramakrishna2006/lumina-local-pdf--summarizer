"""Delete temporary files older than one hour.  Usage: python scripts/cleanup.py"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.core.config import settings  # noqa: E402

cutoff = time.time() - 3600
removed = 0
for path in Path(settings().temp_dir).rglob("*"):
    if path.is_file() and path.name != ".gitkeep" and path.stat().st_mtime < cutoff:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
print(f"Cleanup complete. Removed {removed} file(s).")
