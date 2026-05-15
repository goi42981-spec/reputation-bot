"""Async persistence layer for users, moderators and reputation.

Two backends are supported and chosen automatically based on the connection
string passed to :func:`create_database`:

* ``postgres://`` / ``postgresql://`` URLs use :class:`PostgresDatabase`
  (asyncpg). This is the production backend on Neon, Supabase and other
  hosted Postgres providers.
* Any other value is treated as a SQLite database file path (including the
  in-process ``:memory:`` database) and uses :class:`SqliteDatabase`. This
  is used for local development and tests.

The two backends expose the same public API defined on the abstract
:class:`Database` base class.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import aiosqlite
import asyncpg

from .config import REPUTATION_LIMIT

logger = logging.getLogger(__name__)


SQLITE_SCHEMA = """
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

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id     BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    username    TEXT,
    full_name   TEXT,
    reputation  BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_users_username
    ON users(chat_id, LOWER(username));

CREATE TABLE IF NOT EXISTS moderators (
    chat_id     BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    granted_by  BIGINT NOT NULL,
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


def clamp_reputation(value: int) -> int:
    """Clamp reputation value to ±REPUTATION_LIMIT range."""
    if value > REPUTATION_LIMIT:
        return REPUTATION_LIMIT
    if value < -REPUTATION_LIMIT:
        return -REPUTATION_LIMIT
    return value


class Database(ABC):
    """Abstract async database interface used by the bot.

    Concrete subclasses implement the persistence for a specific backend.
    Use :func:`create_database` to instantiate the right one for a given
    connection string.
    """

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def upsert_user(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        full_name: str | None,
    ) -> None: ...

    @abstractmethod
    async def delete_user(self, chat_id: int, user_id: int) -> bool: ...

    @abstractmethod
    async def get_user_by_id(self, chat_id: int, user_id: int) -> UserRecord | None: ...

    @abstractmethod
    async def get_user_by_username(
        self, chat_id: int, username: str
    ) -> UserRecord | None: ...

    @abstractmethod
    async def top_users(self, chat_id: int, limit: int) -> list[UserRecord]: ...

    @abstractmethod
    async def adjust_reputation(self, chat_id: int, user_id: int, delta: int) -> int: ...

    @abstractmethod
    async def add_moderator(self, chat_id: int, user_id: int, granted_by: int) -> bool: ...

    @abstractmethod
    async def remove_moderator(self, chat_id: int, user_id: int) -> bool: ...

    @abstractmethod
    async def is_moderator(self, chat_id: int, user_id: int) -> bool: ...

    @abstractmethod
    async def list_moderators(self, chat_id: int) -> list[int]: ...


# ---------- SQLite backend ----------


class SqliteDatabase(Database):
    """SQLite-backed implementation used for local dev and tests."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SQLITE_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _c(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected; call connect() first.")
        return self._conn

    async def upsert_user(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        full_name: str | None,
    ) -> None:
        normalized = username.lstrip("@").lower() if username else None
        await self._c.execute(
            """
            INSERT INTO users (chat_id, user_id, username, full_name, reputation)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                full_name = COALESCE(excluded.full_name, users.full_name)
            """,
            (chat_id, user_id, normalized, full_name),
        )
        await self._c.commit()

    async def delete_user(self, chat_id: int, user_id: int) -> bool:
        cur = await self._c.execute(
            "DELETE FROM users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await self._c.commit()
        return cur.rowcount > 0

    async def get_user_by_id(self, chat_id: int, user_id: int) -> UserRecord | None:
        async with self._c.execute(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_user(row)

    async def get_user_by_username(
        self, chat_id: int, username: str
    ) -> UserRecord | None:
        normalized = username.lstrip("@").lower()
        async with self._c.execute(
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
        async with self._c.execute(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = ?
            ORDER BY reputation DESC,
                     COALESCE(username, full_name, CAST(user_id AS TEXT)) ASC
            LIMIT ?
            """,
            (chat_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [user for user in (_row_to_user(row) for row in rows) if user is not None]

    async def adjust_reputation(self, chat_id: int, user_id: int, delta: int) -> int:
        user = await self.get_user_by_id(chat_id, user_id)
        if user is None:
            raise LookupError(f"user {user_id} is not registered in chat {chat_id}")

        new_value = clamp_reputation(user.reputation + delta)
        await self._c.execute(
            "UPDATE users SET reputation = ? WHERE chat_id = ? AND user_id = ?",
            (new_value, chat_id, user_id),
        )
        await self._c.commit()
        return new_value

    async def add_moderator(self, chat_id: int, user_id: int, granted_by: int) -> bool:
        cur = await self._c.execute(
            """
            INSERT INTO moderators (chat_id, user_id, granted_by)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO NOTHING
            """,
            (chat_id, user_id, granted_by),
        )
        await self._c.commit()
        return cur.rowcount > 0

    async def remove_moderator(self, chat_id: int, user_id: int) -> bool:
        cur = await self._c.execute(
            "DELETE FROM moderators WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await self._c.commit()
        return cur.rowcount > 0

    async def is_moderator(self, chat_id: int, user_id: int) -> bool:
        async with self._c.execute(
            "SELECT 1 FROM moderators WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        return row is not None

    async def list_moderators(self, chat_id: int) -> list[int]:
        async with self._c.execute(
            "SELECT user_id FROM moderators WHERE chat_id = ?",
            (chat_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [int(row["user_id"]) for row in rows]


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


# ---------- PostgreSQL backend ----------


class PostgresDatabase(Database):
    """PostgreSQL-backed implementation used in production.

    Built on top of :mod:`asyncpg` with a small connection pool. Designed to
    work with hosted providers like Neon, Supabase and Render Postgres.

    The connection URL must be a standard ``postgres://`` or
    ``postgresql://`` URI. SSL is required by most cloud providers and is
    enabled by default unless ``sslmode=disable`` (or ``ssl=false``) is
    explicitly present in the URL.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = _normalize_postgres_dsn(dsn)
        self._ssl_required = _postgres_ssl_required(dsn)
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        kwargs: dict[str, Any] = {
            "min_size": 1,
            "max_size": 5,
            "command_timeout": 30.0,
        }
        if self._ssl_required:
            kwargs["ssl"] = "require"
        self._pool = await asyncpg.create_pool(self._dsn, **kwargs)
        async with self._pool.acquire() as conn:
            await conn.execute(POSTGRES_SCHEMA)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database is not connected; call connect() first.")
        return self._pool

    async def upsert_user(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        full_name: str | None,
    ) -> None:
        normalized = username.lstrip("@").lower() if username else None
        await self._p.execute(
            """
            INSERT INTO users (chat_id, user_id, username, full_name, reputation)
            VALUES ($1, $2, $3, $4, 0)
            ON CONFLICT (chat_id, user_id) DO UPDATE SET
                username = COALESCE(EXCLUDED.username, users.username),
                full_name = COALESCE(EXCLUDED.full_name, users.full_name)
            """,
            chat_id,
            user_id,
            normalized,
            full_name,
        )

    async def delete_user(self, chat_id: int, user_id: int) -> bool:
        status = await self._p.execute(
            "DELETE FROM users WHERE chat_id = $1 AND user_id = $2",
            chat_id,
            user_id,
        )
        return _affected_rows(status) > 0

    async def get_user_by_id(self, chat_id: int, user_id: int) -> UserRecord | None:
        row = await self._p.fetchrow(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = $1 AND user_id = $2
            """,
            chat_id,
            user_id,
        )
        return _record_to_user(row)

    async def get_user_by_username(
        self, chat_id: int, username: str
    ) -> UserRecord | None:
        normalized = username.lstrip("@").lower()
        row = await self._p.fetchrow(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = $1 AND LOWER(username) = $2
            """,
            chat_id,
            normalized,
        )
        return _record_to_user(row)

    async def top_users(self, chat_id: int, limit: int) -> list[UserRecord]:
        rows = await self._p.fetch(
            """
            SELECT chat_id, user_id, username, full_name, reputation
            FROM users
            WHERE chat_id = $1
            ORDER BY reputation DESC,
                     COALESCE(username, full_name, user_id::text) ASC
            LIMIT $2
            """,
            chat_id,
            limit,
        )
        return [user for user in (_record_to_user(row) for row in rows) if user is not None]

    async def adjust_reputation(self, chat_id: int, user_id: int, delta: int) -> int:
        # Apply delta + clamp atomically inside the DB so concurrent updates
        # behave correctly.
        row = await self._p.fetchrow(
            """
            UPDATE users
            SET reputation = LEAST(
                $1::bigint,
                GREATEST(-$1::bigint, reputation + $2::bigint)
            )
            WHERE chat_id = $3 AND user_id = $4
            RETURNING reputation
            """,
            REPUTATION_LIMIT,
            delta,
            chat_id,
            user_id,
        )
        if row is None:
            raise LookupError(f"user {user_id} is not registered in chat {chat_id}")
        return int(row["reputation"])

    async def add_moderator(self, chat_id: int, user_id: int, granted_by: int) -> bool:
        status = await self._p.execute(
            """
            INSERT INTO moderators (chat_id, user_id, granted_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (chat_id, user_id) DO NOTHING
            """,
            chat_id,
            user_id,
            granted_by,
        )
        return _affected_rows(status) > 0

    async def remove_moderator(self, chat_id: int, user_id: int) -> bool:
        status = await self._p.execute(
            "DELETE FROM moderators WHERE chat_id = $1 AND user_id = $2",
            chat_id,
            user_id,
        )
        return _affected_rows(status) > 0

    async def is_moderator(self, chat_id: int, user_id: int) -> bool:
        row = await self._p.fetchrow(
            "SELECT 1 FROM moderators WHERE chat_id = $1 AND user_id = $2",
            chat_id,
            user_id,
        )
        return row is not None

    async def list_moderators(self, chat_id: int) -> list[int]:
        rows = await self._p.fetch(
            "SELECT user_id FROM moderators WHERE chat_id = $1",
            chat_id,
        )
        return [int(row["user_id"]) for row in rows]


def _record_to_user(row: asyncpg.Record | None) -> UserRecord | None:
    if row is None:
        return None
    return UserRecord(
        chat_id=int(row["chat_id"]),
        user_id=int(row["user_id"]),
        username=row["username"],
        full_name=row["full_name"],
        reputation=int(row["reputation"]),
    )


_STATUS_RE = re.compile(r"^(INSERT|UPDATE|DELETE)(?:\s+\d+)?\s+(\d+)$")


def _affected_rows(status: str) -> int:
    """Parse the ``ExecuteCompleted`` tag asyncpg returns from execute()."""
    match = _STATUS_RE.match(status.strip())
    if not match:
        return 0
    return int(match.group(2))


def _normalize_postgres_dsn(dsn: str) -> str:
    """Strip query parameters that asyncpg doesn't understand.

    Neon and other providers commonly include ``sslmode=require`` and
    ``channel_binding=require`` in the connection string. asyncpg expects
    SSL configuration to be passed separately, so we drop those params.
    """
    if "?" not in dsn:
        return dsn
    base, _, query = dsn.partition("?")
    drop = {"sslmode", "channel_binding", "ssl"}
    kept: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if key in drop:
            continue
        kept.append(pair)
    return base if not kept else f"{base}?{'&'.join(kept)}"


def _postgres_ssl_required(dsn: str) -> bool:
    """Decide whether SSL should be enabled for this DSN.

    Defaults to True (most managed providers require it). Honours an
    explicit ``sslmode=disable`` or ``ssl=false`` query parameter.
    """
    if "?" not in dsn:
        return True
    query = dsn.split("?", 1)[1]
    for pair in query.split("&"):
        key, _, value = pair.partition("=")
        key = key.strip().lower()
        value = value.strip().lower()
        if key == "sslmode" and value == "disable":
            return False
        if key == "ssl" and value in {"false", "off", "0", "disable"}:
            return False
    return True


# ---------- factory ----------


def create_database(url_or_path: str) -> Database:
    """Build the right :class:`Database` subclass for a given connection string."""
    if url_or_path.startswith(("postgres://", "postgresql://")):
        return PostgresDatabase(url_or_path)
    return SqliteDatabase(url_or_path)
