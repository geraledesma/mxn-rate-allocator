"""Entry point for the FastAPI web app (localhost dev).

Usage:
    python web_app.py
    # or:
    uvicorn src.rate_allocator.web.app:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from rate_allocator.web.app import run

if __name__ == "__main__":
    run()
