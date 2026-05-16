"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Hard limit on reputation points per user, as specified in the requirements.
REPUTATION_LIMIT: int = 5000

# Inline-button values offered when adjusting reputation.
POINT_OPTIONS: tuple[int, ...] = (1, 5, 10, 20, 50, 100, 500)

DEFAULT_SQLITE_PATH = "reputation.db"


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    bot_token: str
    database_url: str
    super_owner_id: int | None
    allowed_chat_ids: frozenset[int]

    @classmethod
    def from_env(cls) -> Config:
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN environment variable is required. "
                "Get a token from @BotFather and set it via BOT_TOKEN."
            )

        # Preferred env var is DATABASE_URL (Postgres URI or SQLite path).
        # Legacy DB_PATH is honoured for SQLite-only deployments.
        database_url = (
            os.environ.get("DATABASE_URL", "").strip()
            or os.environ.get("DB_PATH", "").strip()
            or DEFAULT_SQLITE_PATH
        )

        super_owner_raw = os.environ.get("OWNER_ID", "").strip()
        super_owner_id: int | None
        if super_owner_raw:
            try:
                super_owner_id = int(super_owner_raw)
            except ValueError as exc:
                raise RuntimeError(
                    f"OWNER_ID must be an integer Telegram user ID, got {super_owner_raw!r}"
                ) from exc
        else:
            super_owner_id = None

        # ALLOWED_CHAT_IDS: comma- or whitespace-separated list of Telegram chat IDs.
        # Empty (or unset) means "no restriction" — the bot responds in any chat.
        # When non-empty, the bot silently ignores updates from any other chat.
        # Use the /chatid command to discover a chat's ID.
        allowed_chat_raw = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
        allowed: set[int] = set()
        if allowed_chat_raw:
            tokens = [t for t in allowed_chat_raw.replace(",", " ").split() if t]
            for tok in tokens:
                try:
                    allowed.add(int(tok))
                except ValueError as exc:
                    raise RuntimeError(
                        "ALLOWED_CHAT_IDS must be a comma- or whitespace-separated list "
                        f"of integer Telegram chat IDs, got {tok!r}"
                    ) from exc

        return cls(
            bot_token=token,
            database_url=database_url,
            super_owner_id=super_owner_id,
            allowed_chat_ids=frozenset(allowed),
        )
