"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Hard limit on reputation points per user, as specified in the requirements.
REPUTATION_LIMIT: int = 5000

# Inline-button values offered when adjusting reputation.
POINT_OPTIONS: tuple[int, ...] = (1, 5, 10, 20, 50, 100, 500)


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    bot_token: str
    db_path: str
    super_owner_id: int | None

    @classmethod
    def from_env(cls) -> Config:
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN environment variable is required. "
                "Get a token from @BotFather and set it via BOT_TOKEN."
            )

        db_path = os.environ.get("DB_PATH", "reputation.db").strip() or "reputation.db"

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

        return cls(
            bot_token=token,
            db_path=db_path,
            super_owner_id=super_owner_id,
        )
