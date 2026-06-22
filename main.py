"""Standalone runner for the WC26 vote & stats app.

Run:  uvicorn main:app --reload
Then open http://127.0.0.1:8000/wc26
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import wc26

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="WC26 Vote", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(wc26.router)


@app.get("/")
def root():
    # Trang gốc mở thẳng app (cùng HTML với /wc26)
    return wc26.wc26_page()
