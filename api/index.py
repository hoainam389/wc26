"""Vercel serverless entrypoint.

Vercel's Python runtime discovers an ASGI `app` in files under /api. We add the
project root to sys.path so `main`/`wc26` import cleanly, then re-export the app.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402

__all__ = ["app"]
