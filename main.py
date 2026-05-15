"""Top-level entry point for `uvicorn main:app` (used by deploy tooling)."""

from reputation_bot.webhook_app import app

__all__ = ["app"]
