"""Shim so ``uvicorn main:app`` from the repo root still works; implementation lives in ``app.main``."""

from app.main import app

__all__ = ["app"]
