"""Tests for the SQLite-backed database layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from reputation_bot.config import REPUTATION_LIMIT
from reputation_bot.database import Database, clamp_reputation, create_database


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = create_database(str(tmp_path / "test.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


async def test_upsert_and_lookup(db: Database) -> None:
    await db.upsert_user(chat_id=1, user_id=10, username="Alice", full_name="Alice A")
    by_id = await db.get_user_by_id(1, 10)
    assert by_id is not None
    assert by_id.username == "alice"  # stored lowercase
    assert by_id.full_name == "Alice A"
    assert by_id.reputation == 0

    by_name = await db.get_user_by_username(1, "@AliCE")
    assert by_name is not None
    assert by_name.user_id == 10

    # Re-upsert keeps reputation, refreshes name.
    await db.adjust_reputation(1, 10, 100)
    await db.upsert_user(chat_id=1, user_id=10, username="Alice2", full_name="Alice B")
    refreshed = await db.get_user_by_id(1, 10)
    assert refreshed is not None
    assert refreshed.reputation == 100
    assert refreshed.username == "alice2"


async def test_delete_user(db: Database) -> None:
    await db.upsert_user(1, 10, "alice", "Alice")
    assert await db.delete_user(1, 10) is True
    assert await db.delete_user(1, 10) is False
    assert await db.get_user_by_id(1, 10) is None


async def test_adjust_reputation_clamps_to_limit(db: Database) -> None:
    await db.upsert_user(1, 10, "alice", "Alice")
    new = await db.adjust_reputation(1, 10, REPUTATION_LIMIT + 500)
    assert new == REPUTATION_LIMIT

    new = await db.adjust_reputation(1, 10, -(2 * REPUTATION_LIMIT))
    assert new == -REPUTATION_LIMIT


async def test_adjust_reputation_for_unknown_user_raises(db: Database) -> None:
    with pytest.raises(LookupError):
        await db.adjust_reputation(1, 999, 5)


async def test_top_users_ordering(db: Database) -> None:
    await db.upsert_user(1, 10, "alice", "Alice")
    await db.upsert_user(1, 20, "bob", "Bob")
    await db.upsert_user(1, 30, "carol", "Carol")
    await db.adjust_reputation(1, 10, 50)
    await db.adjust_reputation(1, 20, 100)
    await db.adjust_reputation(1, 30, 10)

    top = await db.top_users(1, limit=10)
    assert [u.user_id for u in top] == [20, 10, 30]


async def test_per_chat_isolation(db: Database) -> None:
    await db.upsert_user(1, 10, "alice", "Alice")
    await db.upsert_user(2, 10, "alice", "Alice")
    await db.adjust_reputation(1, 10, 50)

    chat1 = await db.get_user_by_id(1, 10)
    chat2 = await db.get_user_by_id(2, 10)
    assert chat1 is not None and chat2 is not None
    assert chat1.reputation == 50
    assert chat2.reputation == 0


async def test_moderators(db: Database) -> None:
    assert await db.add_moderator(1, 42, granted_by=1) is True
    assert await db.add_moderator(1, 42, granted_by=1) is False  # idempotent
    assert await db.is_moderator(1, 42) is True
    assert await db.is_moderator(1, 43) is False
    assert await db.list_moderators(1) == [42]
    assert await db.remove_moderator(1, 42) is True
    assert await db.is_moderator(1, 42) is False


def test_clamp_reputation_unit() -> None:
    assert clamp_reputation(0) == 0
    assert clamp_reputation(REPUTATION_LIMIT) == REPUTATION_LIMIT
    assert clamp_reputation(REPUTATION_LIMIT + 1) == REPUTATION_LIMIT
    assert clamp_reputation(-REPUTATION_LIMIT - 1) == -REPUTATION_LIMIT
    assert clamp_reputation(-100) == -100
