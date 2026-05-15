"""SQLite-backed persistence for users, moderators and reputation."""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from .config import REPUTATION_LIMIT

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    username    TEXT,
    full_name   TEXT,
    reputation  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_users_username
    ON users(chat_id, LOWER(username));

CREATE TABLE IF NOT EXISTS moderators (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    granted_by  INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
"""


@dataclass(frozen=True)
class UserRecord:
    """A single user's profile in a specific chat."""

    chat_id: int
    user_id: int
    username: str | None
    full_name: str | None
    reputation: int


class Database:
    """Asynchronous SQLite wrapper for bot persistence."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected; call connect() first.")
        return self._conn

    # ---------- users ----------

    async def upsert_user(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        full_name: str | None,
    ) -> None:
        """Insert the user if missing; otherwise refresh username / full_name."""
        normalized = username.lstrip("@").lower() if username else None
        await self.conn.execute(
            """
            INSERT INTO users (chat_id, user_id, username, full_name, reputation)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                full_name = COALESCE(excluded.full_name, users.full_name)
            """,
            (chat_id, user_id, normalized, full_name),
        )
        await self.conn.commit()

    async def delete_user(self, chat_id: int, user_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def get_user_by_id(self, chat_id: int, user_id: int) -> UserRecord | None:
        async with self.conn.execute(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_user(row)

    async def get_user_by_username(self, chat_id: int, username: str) -> UserRecord | None:
        normalized = username.lstrip("@").lower()
        async with self.conn.execute(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = ? AND LOWER(username) = ?
            """,
            (chat_id, normalized),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_user(row)

    async def top_users(self, chat_id: int, limit: int) -> list[UserRecord]:
        async with self.conn.execute(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = ?
            ORDER BY reputation DESC, COALESCE(username, full_name, CAST(user_id AS TEXT)) ASC
            LIMIT ?
            """,
            (chat_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [user for user in (_row_to_user(row) for row in rows) if user is not None]

    async def adjust_reputation(self, chat_id: int, user_id: int, delta: int) -> int:
        """Apply a reputation delta, clamping the result to ±REPUTATION_LIMIT.

        Returns the new reputation. Raises LookupError if the user is not in the database.
        """
        user = await self.get_user_by_id(chat_id, user_id)
        if user is None:
            raise LookupError(f"user {user_id} is not registered in chat {chat_id}")

        new_value = clamp_reputation(user.reputation + delta)
        await self.conn.execute(
            "UPDATE users SET reputation = ? WHERE chat_id = ? AND user_id = ?",
            (new_value, chat_id, user_id),
        )
        await self.conn.commit()
        return new_value

    # ---------- moderators ----------

    async def add_moderator(self, chat_id: int, user_id: int, granted_by: int) -> bool:
        cur = await self.conn.execute(
            """
            INSERT INTO moderators (chat_id, user_id, granted_by)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO NOTHING
            """,
            (chat_id, user_id, granted_by),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def remove_moderator(self, chat_id: int, user_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM moderators WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def is_moderator(self, chat_id: int, user_id: int) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM moderators WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        return row is not None

    async def list_moderators(self, chat_id: int) -> list[int]:
        async with self.conn.execute(
            "SELECT user_id FROM moderators WHERE chat_id = ?",
            (chat_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [int(row["user_id"]) for row in rows]


def clamp_reputation(value: int) -> int:
    """Clamp reputation value to ±REPUTATION_LIMIT range."""
    if value > REPUTATION_LIMIT:
        return REPUTATION_LIMIT
    if value < -REPUTATION_LIMIT:
        return -REPUTATION_LIMIT
    return value


def _row_to_user(row: aiosqlite.Row | None) -> UserRecord | None:
    if row is None:
        return None
    return UserRecord(
        chat_id=int(row["chat_id"]),
        user_id=int(row["user_id"]),
        username=row["username"],
        full_name=row["full_name"],
        reputation=int(row["reputation"]),
    )
